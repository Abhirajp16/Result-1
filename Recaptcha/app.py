import io
import os
import re
import sys
import time
import subprocess
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, send_from_directory, send_file, make_response, jsonify, request
from flask_socketio import SocketIO, emit
import db
from excel_header import HEADER_ROWS, DATA_HEADER_ROW, apply_header

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_SCRIPT = os.path.join(BASE_DIR, "bulk_fetcher_6.py")
DEFAULT_CSV = os.path.join(BASE_DIR, "students.csv")
RAW_DATA = os.path.join(BASE_DIR, "raw_results.csv")
RAW_SUMMARY = os.path.join(BASE_DIR, "raw_summary.csv")
OUTPUT_EXCEL = os.path.join(BASE_DIR, "vtu_results.xlsx")
PY = sys.executable
USN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

current_process = None
fetch_stats = {"total": 0, "success": 0, "fail": 0}
current_run_id = None

app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")


# -----------------------------------------
# FRONTEND ROUTES
# -----------------------------------------
@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/student-record")
def student_record_page():
    resp = make_response(render_template("student_record.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/subject-analytics")
def subject_analytics_page():
    resp = make_response(render_template("subject_analytics.html"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@app.route("/api/subject-analytics")
def api_subject_analytics():
    batch_id = request.args.get("batch_id", "").strip()
    subject_code = request.args.get("subject", "").strip().upper()
    if not batch_id or not subject_code:
        return jsonify({"error": "batch_id and subject required"}), 400
    if not db.is_connected():
        return jsonify({"error": db.status_msg}), 503
    batch, students = db.fetch_batch_with_students(batch_id)
    if batch is None:
        return jsonify({"error": "Batch not found"}), 404
    if batch.get("credits") and students:
        credits_map = {k: float(v) for k, v in batch["credits"].items()}
        students = db.compute_sgpa(students, credits_map)
    result = []
    for s in students:
        for sub in (s.get("subjects") or []):
            if sub.get("code", "").upper() != subject_code:
                continue
            result.append({
                "usn": s.get("usn", ""),
                "name": s.get("name", ""),
                "subject": sub,
            })
            break
    return jsonify({"batch": batch, "subject_code": subject_code, "students": result})


def _grade_of(m):
    if m is None: return "\u2026"
    n = float(m)
    if n >= 90: return "O"
    if n >= 80: return "A+"
    if n >= 70: return "A"
    if n >= 60: return "B+"
    if n >= 55: return "B"
    if n >= 50: return "C"
    if n >= 40: return "P"
    return "F"


@app.route("/download")
def download():
    """Serve the latest vtu_results.xlsx with caching fully disabled so a
    browser can never return a stale copy of a previous run's file."""
    try:
        resp = send_from_directory(
            BASE_DIR, os.path.basename(OUTPUT_EXCEL),
            as_attachment=True, conditional=False
        )
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    except FileNotFoundError:
        return "Excel not generated yet", 404


@app.route("/export-batch/<batch_id>")
def export_batch(batch_id):
    """Regenerate an .xlsx from MongoDB data for a saved batch."""
    batch, students = db.fetch_batch_with_students(batch_id)
    if batch is None or students is None:
        return "Batch not found", 404

    df = students_to_pivot_df(students)
    name_map = _extract_subject_names(students)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, startrow=HEADER_ROWS)
    _style_excel_buffer(buf, df.columns.tolist(), name_map)
    buf.seek(0)

    fname = f"vtu_results_{batch.get('department','')}_{batch.get('semester','')}_{batch.get('scheme','')}_{batch.get('year','')}.xlsx"
    resp = send_file(
        buf, as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        conditional=False
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


def _style_excel_buffer(buf, columns, name_map=None):
    """Apply a clean look to an xlsx already written into buf: college header
    block, merged Subject Name row, bold header on a green fill, frozen panes,
    per-column widths and an autofilter."""
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        buf.seek(0)
        wb = load_workbook(buf)
        ws = wb.active

        head_fill = PatternFill("solid", fgColor="1C7A5E")
        head_font = Font(bold=True, color="FFFFFF", size=11)
        thin = Side(style="thin", color="C8D6CE")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # --- Subject Name row (row 2) — merged across each subject's columns ---
        if name_map:
            subj_font = Font(bold=True, color="065F46", size=10)
            subj_fill = PatternFill("solid", fgColor="D1FAE5")
            code_cols = {}  # code -> [col_indices]
            for i, col in enumerate(columns, start=1):
                if " - " in col:
                    code = col.split(" - ")[0]
                    code_cols.setdefault(code, []).append(i)

            for code, cols in code_cols.items():
                name = name_map.get(code, "")
                if not name or len(cols) < 2:
                    continue
                start_col = cols[0]
                end_col = cols[-1]
                ws.merge_cells(
                    start_row=2, start_column=start_col,
                    end_row=2, end_column=end_col
                )
                cell = ws.cell(row=2, column=start_col)
                cell.value = name
                cell.font = subj_font
                cell.fill = subj_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
                for c in range(start_col, end_col + 1):
                    ws.cell(row=2, column=c).fill = subj_fill
                    ws.cell(row=2, column=c).border = border

        # --- Data header row (row 3) — green fill ---
        for cell in ws[DATA_HEADER_ROW]:
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border

        # --- Column widths ---
        for i, col in enumerate(columns, start=1):
            letter = ws.cell(row=DATA_HEADER_ROW, column=i).column_letter
            if col == "USN":
                ws.column_dimensions[letter].width = 14
            elif col == "Name":
                ws.column_dimensions[letter].width = 28
            elif "Percentage" in col or "Overall" in col:
                ws.column_dimensions[letter].width = 15
            else:
                ws.column_dimensions[letter].width = 12

        # --- Data row borders ---
        for row in ws.iter_rows(min_row=DATA_HEADER_ROW + 1):
            for cell in row:
                cell.border = border

        apply_header(ws, len(columns))
        ws.freeze_panes = f"C{DATA_HEADER_ROW + 1}"
        ws.auto_filter.ref = f"A{DATA_HEADER_ROW}:{get_column_letter(len(columns))}{ws.max_row}"
        buf.seek(0)
        buf.truncate()
        wb.save(buf)
    except Exception as e:
        print("[Warn] Excel styling skipped:", e)


def _grade(marks):
    """Map total marks to a VTU grade (per the standard grade table)."""
    try:
        m = float(marks)
    except (TypeError, ValueError):
        return ""
    if m >= 90:
        return "O"
    if m >= 80:
        return "A+"
    if m >= 70:
        return "A"
    if m >= 60:
        return "B+"
    if m >= 55:
        return "B"
    if m >= 50:
        return "C"
    if m >= 40:
        return "P"
    return "F"


def students_to_pivot_df(students):
    """Turn DB student docs into the same pivot shape as the live Excel.
    Uses reval'd values (final_marks/final_grade) when available,
    falls back to original values."""
    rows = []
    for s in students:
        row = {
            "USN": s.get("usn", ""),
            "Name": s.get("name", ""),
            "Percentage": s.get("percentage"),
        }
        total_obtained = 0
        total_max = 0
        for sub in s.get("subjects", []):
            code = sub.get("code", "")
            # Use reval'd values if subject was revaluated
            is_rv = sub.get("is_revaluated", False)
            int_val = sub.get("internal")
            ext = sub.get("final_marks") if is_rv and sub.get("final_marks") is not None else sub.get("external")
            tot = sub.get("final_total") if is_rv and sub.get("final_total") is not None else (_calc_total(int_val, ext) if ext is not None else sub.get("total"))
            res = sub.get("final_result") if is_rv and sub.get("final_result") else sub.get("result")
            grd = sub.get("final_grade") if is_rv and sub.get("final_grade") else sub.get("grade", _grade(tot))
            row[f"{code} - Internal Marks"] = sub.get("internal")
            row[f"{code} - External Marks"] = ext
            row[f"{code} - Total Marks"] = tot
            row[f"{code} - Grade"] = grd
            row[f"{code} - Result"] = res
            if tot is not None:
                try:
                    total_obtained += int(tot)
                except (TypeError, ValueError):
                    pass
                total_max += 100
        row["Overall Total"] = total_obtained if total_obtained else ""
        row["Overall Max Marks"] = total_max if total_max else ""
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    codes = sorted(set(
        c.split(" - ")[0] for r in rows for c in r.keys() if " - " in c
    ))
    order = ["USN", "Name"]
    for code in codes:
        for suf in ("Internal Marks", "External Marks", "Total Marks", "Grade", "Result"):
            order.append(f"{code} - {suf}")
    order.extend(["Percentage", "Overall Total", "Overall Max Marks"])

    df = pd.DataFrame(rows)
    for col in order:
        if col not in df.columns:
            df[col] = ""
    return df[order].fillna("")


def _extract_subject_names(students):
    """Extract {code: name} map from student docs."""
    name_map = {}
    for s in students:
        for sub in s.get("subjects", []):
            code = sub.get("code", "")
            name = sub.get("subject_name", "")
            if code and name and code not in name_map:
                name_map[code] = name
    return name_map


# -----------------------------------------
# FILTER OPTIONS API (populates Browse dropdowns from the database)
# -----------------------------------------
SEMESTER_PRESETS = [str(s) for s in range(1, 9)]
SCHEME_PRESETS = [str(y) for y in range(2018, 2027)]
YEAR_PRESETS = [str(y) for y in range(2019, 2027)]


def _num_key(v):
    return int(v) if v.isdigit() else float("inf")


def _filter_values(field, presets, reverse=False):
    """Merge static presets with distinct DB values; dedupe; numeric sort."""
    try:
        merged = set(presets) | set(db.distinct_batch_values(field))
    except Exception:
        merged = set(presets)
    return sorted(merged, key=_num_key, reverse=reverse)


@app.route("/api/filters/semesters")
def filters_semesters():
    return jsonify(_filter_values("semester", SEMESTER_PRESETS))


@app.route("/api/filters/schemes")
def filters_schemes():
    return jsonify(_filter_values("scheme", SCHEME_PRESETS, reverse=True))


@app.route("/api/filters/years")
def filters_years():
    return jsonify(_filter_values("year", YEAR_PRESETS))


# -----------------------------------------
# IMPORT CSV
# -----------------------------------------
@socketio.on("import-csv")
def import_csv():
    if not os.path.exists(DEFAULT_CSV):
        emit("log-message", {"data": "[Error] students.csv missing\n"})
        return

    with open(DEFAULT_CSV) as f:
        lines = f.readlines()[1:]

    emit("csv-data", {"usns": "".join(lines)})
    emit("log-message", {"data": f"Imported {len(lines)} USNs\n"})


# -----------------------------------------
# START FETCHING
# -----------------------------------------
@socketio.on("start-fetch")
def start_fetch(msg):
    global fetch_stats, current_process, current_run_id

    usns = msg.get("usns", [])
    vtu_url = msg.get("url", "")

    if current_process and current_process.poll() is None:
        emit("log-message", {"data": "[Error] A fetch is already running. Stop it first.\n"})
        return

    if not usns:
        emit("log-message", {"data": "[Error] No USNs provided.\n"})
        return

    if not vtu_url:
        emit("log-message", {"data": "[Error] No VTU URL provided.\n"})
        return

    # Validate & clean USNs server-side
    clean = []
    skipped = []
    for u in usns:
        u = str(u).strip().upper()
        if USN_PATTERN.match(u):
            clean.append(u)
        else:
            skipped.append(u)

    if skipped:
        emit("log-message", {"data": f"[Warn] Skipped invalid USN entries: {', '.join(skipped)}\n"})
    if not clean:
        emit("log-message", {"data": "[Error] No valid USNs. Format e.g. 1GD23CS001\n"})
        return

    with open(DEFAULT_CSV, "w") as f:
        f.write("USN\n")
        for u in clean:
            f.write(u + "\n")

    fetch_stats = {"total": len(clean), "success": 0, "fail": 0}
    current_run_id = time.strftime("%Y%m%d-%H%M%S")

    emit("log-message", {"data": f"[Run {current_run_id}] Fetch started — {len(clean)} USN(s) from your list.\n"})
    emit("log-message", {"data": f"[Run {current_run_id}] USNs: {', '.join(clean)}\n"})

    # Clear stale outputs from previous runs so old data never leaks into the new fetch
    for f in (RAW_DATA, RAW_SUMMARY, OUTPUT_EXCEL):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
        except PermissionError:
            emit("log-message", {"data": f"[Warn] Could not clear {os.path.basename(f)} — close it if it is open in Excel.\n"})

    socketio.start_background_task(target=run_scraper, vtu_url=vtu_url, total_usns=len(clean), run_id=current_run_id)
    emit("fetch-started", {"total": len(clean), "run_id": current_run_id})


# -----------------------------------------
# STOP FETCHING
# -----------------------------------------
@socketio.on("stop-fetch")
def stop_fetch():
    global current_process
    if current_process and current_process.poll() is None:
        current_process.terminate()
        emit("log-message", {"data": "\n[Stopped] Fetch terminated by user.\n"})
    else:
        emit("log-message", {"data": "\n[Info] No running process to stop.\n"})


def _auto_save_to_db(run_id):
    """Auto-save fetched results to MongoDB with values inferred from USNs."""
    if not db.is_connected():
        return

    if not os.path.exists(RAW_DATA) or not os.path.exists(RAW_SUMMARY):
        return

    try:
        summ = pd.read_csv(RAW_SUMMARY)
        if summ.empty:
            return
    except Exception:
        return

    # Infer values from USN prefix (e.g. 1GD23CS001 -> scheme=2023, dept=CS)
    usns = summ["USN"].astype(str).str.strip().tolist()
    if not usns:
        return

    prefix = re.sub(r"\d+$", "", usns[0])

    # Extract scheme year from USN (digits at position 4-5, e.g. "23" -> 2023)
    scheme_match = re.search(r"(\d{2})[A-Z]{2}\d{3}", prefix)
    if scheme_match:
        yr = int(scheme_match.group(1))
        scheme = str(2000 + yr)
    else:
        scheme = str(datetime.utcnow().year)

    # Extract department code
    dept_match = re.search(r"\d{2}([A-Z]{2})\d{3}$", prefix)
    dept_code = dept_match.group(1) if dept_match else "GEN"
    dept_map = {
        "CS": "Computer Science", "IS": "Information Science",
        "EC": "Electronics", "EE": "Electrical", "ME": "Mechanical",
        "CV": "Civil", "CH": "Chemical", "BT": "Biotech",
        "AI": "AI & ML", "DS": "Data Science",
    }
    department = dept_map.get(dept_code, dept_code)

    # Infer semester from first USN digit
    sem_match = re.match(r"(\d)", usns[0])
    semester = str(int(sem_match.group(1))) if sem_match else "1"

    year = scheme

    socketio.emit("log-message", {
        "data": f"[DB] Auto-saving: year={year}, scheme={scheme}, semester={semester}, dept={department}\n"
    })

    batch_doc, student_docs = build_db_payload(year, scheme, semester, department)
    if batch_doc is None:
        socketio.emit("log-message", {"data": f"[DB] Auto-save skipped: {student_docs}\n"})
        return


    batch_id, added, merged, total = db.save_batch(batch_doc, student_docs)
    if batch_id is None:
        socketio.emit("log-message", {"data": f"[DB] Auto-save failed: {added}\n"})
        return

    socketio.emit("log-message", {
        "data": f"[DB] Auto-saved batch {batch_id} — {total} students.\n"
    })
    socketio.emit("save-to-db-complete", {
        "batch_id": str(batch_id),
        "student_count": total,
        "added_count": added,
        "merged": merged,
    })


# -----------------------------------------
# RUN SCRAPER WITH URL ARG
# -----------------------------------------
def run_scraper(vtu_url, total_usns, run_id):
    global current_process, fetch_stats
    cmd = [PY, BACKEND_SCRIPT, vtu_url, run_id]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=BASE_DIR
    )
    current_process = process
    started = time.time()
    failed_usns = []

    for line in iter(process.stdout.readline, ""):
        socketio.emit("log-message", {"data": line})
        if "[Success] Scraped" in line:
            fetch_stats["success"] += 1
            socketio.emit("fetch-progress", dict(fetch_stats))
        elif "FAILED to fetch" in line:
            fetch_stats["fail"] += 1
            m = re.search(r"FAILED to fetch results for USN: (\S+)", line)
            if m:
                failed_usns.append(m.group(1))
            socketio.emit("fetch-progress", dict(fetch_stats))

    process.wait()
    current_process = None

    complete_data = dict(fetch_stats)
    complete_data["failed"] = failed_usns
    socketio.emit("fetch-complete", complete_data)

    # Explicit write confirmation: only advertise the download if the Excel was
    # actually rewritten during this run (mtime newer than when we started).
    fresh = False
    if os.path.exists(OUTPUT_EXCEL):
        try:
            fresh = os.path.getmtime(OUTPUT_EXCEL) >= started - 1
        except OSError:
            fresh = False

    if fresh:
        mtime = os.path.getmtime(OUTPUT_EXCEL)
        socketio.emit("log-message", {"data": f"[Run {run_id}] Excel verified fresh (mtime {time.strftime('%H:%M:%S', time.localtime(mtime))}).\n"})
        socketio.emit("download-ready")
    else:
        socketio.emit("log-message", {"data": f"\n[Run {run_id}] [Error] No fresh results were generated — check the logs above (vtu_results.xlsx may be open in Excel, or all USNs failed).\n"})


# -----------------------------------------
# MONGODB EVENTS
# -----------------------------------------
@socketio.on("get-db-status")
def get_db_status():
    emit("db-status", {"connected": db.is_connected(), "message": db.status_msg})


def _to_num(v):
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


def _grade(marks):
    try:
        m = float(marks)
    except (TypeError, ValueError):
        return ""
    if m >= 90: return "O"
    if m >= 80: return "A+"
    if m >= 70: return "A"
    if m >= 60: return "B+"
    if m >= 55: return "B"
    if m >= 50: return "C"
    if m >= 40: return "P"
    return "F"


def _calc_total(internal, external):
    """TOTAL = INTERNAL + EXTERNAL. Returns None if either is missing."""
    try:
        return int(internal) + int(external)
    except (TypeError, ValueError):
        return None


def build_db_payload(year, scheme, semester, department):
    """Read the just-fetched raw CSVs and build (batch_doc, student_docs).
    Returns (None, error_message) on any failure."""
    if not os.path.exists(RAW_DATA) or not os.path.exists(RAW_SUMMARY):
        return None, "No fetched data found. Run a fetch first."

    try:
        subs = pd.read_csv(RAW_DATA)
        summ = pd.read_csv(RAW_SUMMARY)
    except Exception as e:
        return None, f"Could not read raw CSVs: {e}"

    if subs.empty or summ.empty:
        return None, "Raw CSVs are empty — nothing to save."

    subs["USN"] = subs["USN"].astype(str).str.strip().str.upper()
    summ["USN"] = summ["USN"].astype(str).str.strip().str.upper()
    summ_map = {r["USN"]: r for _, r in summ.iterrows()}

    subject_codes = sorted(subs["Subject Code"].dropna().unique().tolist())
    usns = sorted(subs["USN"].dropna().unique().tolist())
    prefix = re.sub(r"\d+$", "", usns[0]) if usns else ""

    student_docs = []
    for usn in usns:
        group = subs[subs["USN"] == usn]
        name = ""
        if not group.empty:
            name = str(group.iloc[0].get("Name", "") or "").strip()
        srow = summ_map.get(usn)
        percentage = None
        if srow is not None and pd.notna(srow.get("percentage")):
            percentage = round(float(srow["percentage"]), 2)

        subjects = []
        has_fail = False
        for _, r in group.iterrows():
            result = str(r.get("Result", "") or "").strip()
            if result == "F":
                has_fail = True
            total_marks = _to_num(r.get("Total Marks"))
            subjects.append({
                "code": str(r["Subject Code"]).strip(),
                "subject_name": str(r.get("Subject Name", "") or "").strip(),
                "internal": _to_num(r.get("Internal Marks")),
                "external": _to_num(r.get("External Marks")),
                "total": total_marks,
                "grade": _grade(total_marks),
                "result": result,
            })

        student_docs.append({
            "usn": usn,
            "name": name,
            "subjects": subjects,
            "percentage": percentage,
            "result_status": "FAIL" if has_fail else "PASS",
        })

    batch_doc = {
        "year": str(year).strip(),
        "scheme": str(scheme).strip(),
        "semester": str(semester).strip(),
        "department": str(department).strip(),
        "saved_at": datetime.utcnow(),
        "usn_prefix": prefix,
        "student_count": len(student_docs),
        "subjects": subject_codes,
        "run_id": current_run_id,
    }
    return batch_doc, student_docs


@socketio.on("save-to-db")
def save_to_db(data):
    year = str(data.get("year", "")).strip()
    scheme = str(data.get("scheme", "")).strip()
    semester = str(data.get("semester", "")).strip()
    department = str(data.get("department", "")).strip()
    target_id = str(data.get("target_batch_id", "") or "").strip()

    if not db.is_connected():
        emit("log-message", {"data": f"[DB ERROR] MongoDB not available: {db.status_msg}\n"})
        return

    if target_id:
        batch = db.fetch_batch(target_id)
        if batch is None:
            emit("log-message", {"data": f"[DB ERROR] Target batch {target_id} not found.\n"})
            return
        year = str(batch.get("year", "") or "").strip()
        scheme = str(batch.get("scheme", "") or "").strip()
        semester = str(batch.get("semester", "") or "").strip()
        department = str(batch.get("department", "") or "").strip()

    if not (year and scheme and semester and department):
        emit("log-message", {"data": "[DB ERROR] year, scheme, semester and department are all required.\n"})
        return

    batch_doc, student_docs = build_db_payload(year, scheme, semester, department)
    if batch_doc is None:
        emit("log-message", {"data": f"[DB ERROR] {student_docs}\n"})
        return

    if target_id:
        batch_id, added, merged, total = db.merge_into_batch(target_id, batch_doc, student_docs)
    else:
        batch_id, added, merged, total = db.save_batch(batch_doc, student_docs)

    if batch_id is None:
        emit("log-message", {"data": f"[DB ERROR] Save failed: {added}\n"})
        return

    if merged or target_id:
        emit("log-message", {
            "data": f"[DB] Merged into batch {batch_id} — {added} new student(s), total {total}.\n"
        })
    else:
        emit("log-message", {
            "data": f"[DB] Saved new batch {batch_id} — {total} students, {len(batch_doc['subjects'])} subjects.\n"
        })
    emit("save-to-db-complete", {
        "batch_id": str(batch_id),
        "student_count": total,
        "added_count": added,
        "merged": merged,
    })


@socketio.on("get-batches")
def get_batches():
    if not db.is_connected():
        emit("batches", {"batches": [], "error": db.status_msg})
        return
    batches = db.fetch_batches()
    emit("batches", {"batches": batches, "error": None})


@socketio.on("get-batch-results")
def get_batch_results(data):
    batch_id = str(data.get("batch_id", ""))
    if not db.is_connected():
        emit("batch-results", {"batch": None, "students": [], "error": db.status_msg})
        return
    batch, students = db.fetch_batch_with_students(batch_id)
    if batch and batch.get("credits") and students:
        credits_map = {k: float(v) for k, v in batch["credits"].items()}
        students = db.compute_sgpa(students, credits_map)
    emit("batch-results", {"batch": batch, "students": students, "error": None})


@app.route("/api/student-record/<usn>")
def api_student_record(usn):
    usn = usn.strip().upper()
    if not USN_PATTERN.match(usn):
        return jsonify({"error": "Invalid USN format"}), 400
    if not db.is_connected():
        return jsonify({"error": db.status_msg}), 503
    record = db.fetch_student_record(usn)
    if record is None:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(record)


# -----------------------------------------
# DELETE BATCH
# -----------------------------------------
@socketio.on("delete-batch")
def delete_batch_handler(data):
    batch_id = str(data.get("batch_id", ""))
    if not batch_id:
        emit("batch-deleted", {"ok": False, "error": "No batch ID"})
        return
    if not db.is_connected():
        emit("batch-deleted", {"ok": False, "error": db.status_msg})
        return
    ok, err = db.delete_batch(batch_id)
    emit("batch-deleted", {"ok": ok, "error": err, "batch_id": batch_id})


# -----------------------------------------
# CREDITS & SGPA
# -----------------------------------------
@socketio.on("get-fetched-subjects")
def get_fetched_subjects():
    if not os.path.exists(RAW_DATA):
        emit("fetched-subjects", {"subjects": []})
        return
    try:
        df = pd.read_csv(RAW_DATA)
        subjects = sorted(df["Subject Code"].dropna().unique().tolist())
        emit("fetched-subjects", {"subjects": subjects})
    except Exception:
        emit("fetched-subjects", {"subjects": []})

@socketio.on("save-credits")
def save_credits_handler(data):
    batch_id = str(data.get("batch_id", ""))
    credits = data.get("credits", {})
    if not batch_id:
        emit("credits-saved", {"ok": False, "error": "No batch ID"})
        return
    if not db.is_connected():
        emit("credits-saved", {"ok": False, "error": db.status_msg})
        return
    ok, err = db.save_credits(batch_id, credits)
    if ok:
        students = db.fetch_students(batch_id)
        credits_map = {k: float(v) for k, v in credits.items()}
        students = db.compute_sgpa(students, credits_map)
        # Store SGPA back to each student document
        for s in students:
            if s.get("sgpa") is not None and s.get("id"):
                try:
                    from supabase import create_client
                    db.client.table("student_results").update(
                        {"sgpa": s["sgpa"]}
                    ).eq("id", s["id"]).execute()
                except Exception:
                    pass
        avg_sgpa = round(sum(s["sgpa"] for s in students if s.get("sgpa") is not None) /
                         max(1, sum(1 for s in students if s.get("sgpa") is not None)), 2)
        emit("credits-saved", {"ok": True, "batch_id": batch_id,
                               "avg_sgpa": avg_sgpa, "student_count": len(students)})
    else:
        emit("credits-saved", {"ok": False, "error": err})


@socketio.on("get-credits")
def get_credits_handler(data):
    batch_id = str(data.get("batch_id", ""))
    if not batch_id or not db.is_connected():
        emit("credits-data", {"credits": {}, "students": []})
        return
    credits = db.get_credits(batch_id)
    students = db.fetch_students(batch_id)
    if credits:
        credits_map = {k: float(v) for k, v in credits.items()}
        students = db.compute_sgpa(students, credits_map)
    emit("credits-data", {"batch_id": batch_id, "credits": credits, "students": students})


# -----------------------------------------
# REVALUATION
# -----------------------------------------
import subprocess, signal

_rv_process = None

@socketio.on("start-reval-fetch")
def start_reval_fetch(msg):
    global _rv_process
    vtu_url = msg.get("url", "")
    batch_id = msg.get("batch_id", "")
    usns = msg.get("usns", [])

    if not vtu_url or not batch_id or not usns:
        emit("log-message", {"data": "[Error] URL, batch, and USNs required.\n"})
        return

    # Write USNs to a temp CSV for the scraper
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reval_students.csv")
    with open(csv_path, "w") as f:
        f.write("USN\n")
        for u in usns:
            f.write(u.strip().upper() + "\n")

    emit("log-message", {"data": f"[Reval] Starting fetch for {len(usns)} USN(s)...\n"})

    def _run():
        global _rv_process
        rc = -1
        try:
            run_id = time.strftime("rv-%Y%m%d-%H%M%S")
            cmd = [sys.executable, "bulk_fetcher_6.py", vtu_url, run_id, "--reval", "--batch-id", batch_id]
            socketio.emit("log-message", {"data": f"[Reval] CMD: {' '.join(cmd)}\n"})
            socketio.emit("log-message", {"data": f"[Reval] CSV: {csv_path}\n"})
            _rv_process = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            for line in _rv_process.stdout:
                socketio.emit("log-message", {"data": line})
            rc = _rv_process.wait()
        except Exception as e:
            socketio.emit("log-message", {"data": f"[Error] {e}\n"})
        # Always emit complete so UI shows Compare button
        socketio.emit("log-message", {"data": f"\n[Reval] Done (exit code {rc}).\n"})
        socketio.emit("reval-fetch-complete", {"success": len(usns), "fail": 0})

    socketio.start_background_task(target=_run)


@socketio.on("compare-reval")
def compare_reval(data):
    try:
        usn = str(data.get("usn", "")).strip().upper()
        batch_id = str(data.get("batch_id", ""))
        if not usn or not batch_id:
            emit("reval-compare", {"error": "USN and batch required"})
            return

        # Fetch old student from DB
        old_student = None
        students = db.fetch_students(batch_id)
        for s in students:
            if s.get("usn", "").upper() == usn:
                old_student = s
                break

        if not old_student:
            emit("reval-compare", {"error": f"USN {usn} not found in batch"})
            return

        # Read reval data from CSV — only contains reval-applied subjects
        rv_map = {}
        raw_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_results_rv.csv")
        if os.path.exists(raw_data_path):
            try:
                df = pd.read_csv(raw_data_path)
                df["USN"] = df["USN"].astype(str).str.strip().str.upper()
                usn_df = df[df["USN"] == usn]
                for _, r in usn_df.iterrows():
                    code = str(r.get("Subject Code", "")).strip()
                    rv_map[code] = {
                        "internal": _to_num(r.get("Internal Marks")),
                        "external": _to_num(r.get("External Marks")),
                        "old_marks": _to_num(r.get("Old Marks") or r.get("External Marks")),
                        "old_result": str(r.get("Old Result") or r.get("Result", "") or "").strip(),
                        "rv_marks": _to_num(r.get("RV Marks")),
                        "rv_result": str(r.get("RV Result", "") or "").strip(),
                        "final_marks": _to_num(r.get("Final Marks")),
                        "final_result": str(r.get("Final Result", "") or "").strip(),
                        "subject_name": str(r.get("Subject Name", "") or "").strip(),
                    }
            except Exception as e:
                print("[Reval] CSV read error:", e)
                emit("reval-compare", {"error": f"Failed to read reval data: {e}"})
                return

        if not rv_map:
            emit("reval-compare", {"error": f"No reval data found for {usn}"})
            return

        # Build new_student: ALL subjects from old, reval ones updated
        old_subjects = old_student.get("subjects", [])
        new_subjects = []
        for subj in old_subjects:
            code = subj.get("code", "")
            # Use existing originals if subject was already reval'd before
            orig_ext = subj.get("original_external") or subj.get("external")
            orig_total = subj.get("original_total") or subj.get("total")
            orig_result = subj.get("original_result") or subj.get("result", "")
            orig_grade = subj.get("original_grade") or subj.get("grade", "")

            if code in rv_map:
                rv = rv_map[code]
                # TOTAL = INTERNAL + REVALUATION EXTERNAL
                rv_ext = rv["rv_marks"] if rv["rv_marks"] is not None else (rv["final_marks"] if rv["final_marks"] is not None else orig_ext)
                int_val = rv["internal"] if rv["internal"] is not None else subj.get("internal")
                final_ext = rv_ext
                final_total = _calc_total(int_val, final_ext)
                if final_total is None:
                    final_total = orig_total
                final_r = rv["final_result"] or orig_result
                if not final_r:
                    final_r = rv["rv_result"] or orig_result
                final_g = _grade(final_total)
                new_subjects.append({
                    "code": code,
                    "subject_name": rv["subject_name"] or subj.get("subject_name", ""),
                    "internal": int_val,
                    "external": orig_ext,
                    "total": orig_total,
                    "result": orig_result,
                    "grade": orig_grade,
                    "rv_marks": rv["rv_marks"],
                    "rv_result": rv["rv_result"],
                    "final_marks": final_ext,
                    "final_total": final_total,
                    "final_result": final_r,
                    "final_grade": final_g,
                    "is_revaluated": True,
                    "original_external": orig_ext,
                    "original_total": orig_total,
                    "original_result": orig_result,
                    "original_grade": orig_grade,
                })
            else:
                new_subjects.append({
                    "code": code,
                    "subject_name": subj.get("subject_name", ""),
                    "internal": subj.get("internal"),
                    "external": subj.get("external"),
                    "total": subj.get("total"),
                    "result": subj.get("result", ""),
                    "grade": subj.get("grade", _grade(subj.get("total"))),
                    "rv_marks": None,
                    "rv_result": "",
                    "final_marks": None,
                    "final_result": "",
                    "final_grade": "",
                    "is_revaluated": False,
                    "original_external": None,
                    "original_total": None,
                    "original_result": None,
                    "original_grade": None,
                })

        new_student = {"usn": usn, "name": old_student.get("name", ""), "subjects": new_subjects}
        emit("reval-compare", {"usn": usn, "old_student": old_student, "new_student": new_student, "batch_id": batch_id})
    except Exception as e:
        print("[Reval] compare_reval error:", e)
        emit("reval-compare", {"error": str(e)})


@socketio.on("update-reval-result")
def update_reval_result(data):
    usn = str(data.get("usn", "")).strip().upper()
    batch_id = str(data.get("batch_id", ""))
    selected_codes = data.get("selected_codes")  # None = update all, list = update only those
    print(f"[Reval] selected_codes={selected_codes} type={type(selected_codes)}")
    if not usn or not batch_id:
        emit("reval-updated", {"ok": False, "error": "USN and batch required"})
        return

    # Read new data from raw CSV
    raw_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw_results_rv.csv")
    if not os.path.exists(raw_data_path):
        emit("reval-updated", {"ok": False, "error": "No reval data file found"})
        return

    try:
        df = pd.read_csv(raw_data_path)
        df["USN"] = df["USN"].astype(str).str.strip().str.upper()
        usn_df = df[df["USN"] == usn]
        if usn_df.empty:
            emit("reval-updated", {"ok": False, "error": f"No reval data for {usn}"})
            return

        # Read reval data for this USN
        rv_map = {}
        name = str(usn_df.iloc[0].get("Name", "") or "").strip()
        for _, r in usn_df.iterrows():
            code = str(r.get("Subject Code", "")).strip()
            rv_map[code] = {
                "internal": _to_num(r.get("Internal Marks")),
                "external": _to_num(r.get("External Marks")),
                "old_marks": _to_num(r.get("Old Marks") or r.get("External Marks")),
                "old_result": str(r.get("Old Result") or r.get("Result", "") or "").strip(),
                "rv_marks": _to_num(r.get("RV Marks")),
                "rv_result": str(r.get("RV Result", "") or "").strip(),
                "final_marks": _to_num(r.get("Final Marks")),
                "final_result": str(r.get("Final Result", "") or "").strip(),
                "subject_name": str(r.get("Subject Name", "") or "").strip(),
            }
        print(f"[Reval] rv_map keys={list(rv_map.keys())}")

        # Fetch old student to get ALL subjects
        old_student = None
        students = db.fetch_students(batch_id)
        for s in students:
            if s.get("usn", "").upper() == usn:
                old_student = s
                break

        if not old_student:
            emit("reval-updated", {"ok": False, "error": f"USN {usn} not found in batch"})
            return

        old_subjects = old_student.get("subjects", [])
        name = name or old_student.get("name", "")
        subjects = []
        for subj in old_subjects:
            code = subj.get("code", "")
            # Existing originals (in case this subject was already reval'd before)
            orig_ext = subj.get("original_external") or subj.get("external")
            orig_total = subj.get("original_total") or subj.get("total")
            orig_result = subj.get("original_result") or subj.get("result", "")
            orig_grade = subj.get("original_grade") or subj.get("grade", "")

            # If selected_codes is provided, only update subjects in that list
            if selected_codes == "auto":
                # Auto mode: only apply reval if new total > old total (improved)
                rv = rv_map.get(code)
                if rv:
                    rv_ext = rv["rv_marks"] if rv["rv_marks"] is not None else (rv["final_marks"] if rv["final_marks"] is not None else orig_ext)
                    int_val = rv["internal"] if rv["internal"] is not None else subj.get("internal")
                    new_total = _calc_total(int_val, rv_ext)
                    should_apply_reval = new_total is not None and orig_total is not None and new_total > orig_total
                else:
                    should_apply_reval = False
            else:
                should_apply_reval = code in rv_map and (selected_codes is None or code in selected_codes)
            if should_apply_reval:
                print(f"[Reval] APPLY reval for {code} (in_rv_map={code in rv_map}, selected={selected_codes is None or code in selected_codes})")
            elif code in rv_map:
                print(f"[Reval] SKIP reval for {code} (not in selected_codes={selected_codes})")

            if should_apply_reval:
                rv = rv_map[code]
                # TOTAL = INTERNAL + REVALUATION EXTERNAL
                rv_ext = rv["rv_marks"] if rv["rv_marks"] is not None else (rv["final_marks"] if rv["final_marks"] is not None else orig_ext)
                int_val = rv["internal"] if rv["internal"] is not None else subj.get("internal")
                final_ext = rv_ext
                final_total = _calc_total(int_val, final_ext)
                if final_total is None:
                    final_total = orig_total
                final_r = rv["final_result"] or orig_result
                if not final_r:
                    final_r = rv["rv_result"] or orig_result
                final_g = _grade(final_total)
                subjects.append({
                    "code": code,
                    "subject_name": rv["subject_name"] or subj.get("subject_name", ""),
                    "internal": int_val,
                    "external": orig_ext,
                    "total": orig_total,
                    "result": orig_result,
                    "grade": orig_grade,
                    "rv_marks": rv["rv_marks"],
                    "rv_result": rv["rv_result"],
                    "final_marks": final_ext,
                    "final_total": final_total,
                    "final_result": final_r,
                    "final_grade": final_g,
                    "is_revaluated": True,
                    "original_external": orig_ext,
                    "original_total": orig_total,
                    "original_result": orig_result,
                    "original_grade": orig_grade,
                })
            else:
                # Non-reval'd OR reval'd but not selected: keep original DB data exactly
                subjects.append({
                    "code": code,
                    "subject_name": subj.get("subject_name", ""),
                    "internal": subj.get("internal"),
                    "external": subj.get("external"),
                    "total": subj.get("total"),
                    "result": subj.get("result", ""),
                    "grade": subj.get("grade", _grade(subj.get("total"))),
                    "rv_marks": None,
                    "rv_result": "",
                    "final_marks": None,
                    "final_result": "",
                    "final_grade": "",
                    "is_revaluated": False,
                })

        # Determine pass/fail using the BEST available result for each subject
        has_fail = False
        for s in subjects:
            best_result = s.get("final_result") or s.get("result", "")
            if best_result == "F":
                has_fail = True
                break

        ok = db.update_student_result_reval(batch_id, usn, name, subjects, "FAIL" if has_fail else "PASS")
        if ok:
            emit("reval-updated", {"ok": True, "usn": usn, "batch_id": batch_id})
        else:
            emit("reval-updated", {"ok": False, "error": "DB update failed"})
    except Exception as e:
        emit("reval-updated", {"ok": False, "error": str(e)})


# -----------------------------------------
if __name__ == "__main__":
    db.init_db()
    print(f"[Supabase] status={db.status} — {db.status_msg}")
    socketio.run(app, host="127.0.0.1", port=5000, allow_unsafe_werkzeug=True, use_reloader=False)
