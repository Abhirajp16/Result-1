"""Supabase (PostgreSQL) persistence layer for the VTU result fetcher.

Reads SUPABASE_URL and SUPABASE_KEY from the .env file (python-dotenv).
If Supabase is not configured or unreachable, every function degrades
gracefully (returns empty results / error messages) — the app keeps working.
"""

import os
import json
import threading
import time
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    _dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_dir, ".env"))
except Exception:
    pass

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

client = None
status = "disabled"
status_msg = "Supabase not configured (set SUPABASE_URL and SUPABASE_KEY in .env)"

_PLACEHOLDER_MARKERS = ("PASTE", "<", "your-", "xxx")

GRADE_POINTS = {"O": 10, "A+": 9, "A": 8, "B+": 7, "B": 6, "C": 5, "P": 4, "F": 0}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fetch_batches (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    year TEXT,
    scheme TEXT,
    semester TEXT,
    department TEXT,
    subjects JSONB DEFAULT '[]',
    credits JSONB DEFAULT '{}',
    student_count INTEGER DEFAULT 0,
    usn_prefix TEXT,
    run_id TEXT,
    saved_at TIMESTAMPTZ DEFAULT now(),
    credits_updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS student_results (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    batch_id TEXT REFERENCES fetch_batches(id) ON DELETE CASCADE,
    usn TEXT,
    name TEXT,
    subjects JSONB DEFAULT '[]',
    percentage REAL,
    sgpa REAL,
    result_status TEXT
);

CREATE INDEX IF NOT EXISTS idx_students_batch ON student_results(batch_id);
CREATE INDEX IF NOT EXISTS idx_students_usn ON student_results(usn);
"""


def init_db():
    global client, status, status_msg

    if not SUPABASE_URL or any(m in SUPABASE_URL for m in _PLACEHOLDER_MARKERS):
        status = "disabled"
        status_msg = "Supabase not configured — paste your SUPABASE_URL and SUPABASE_KEY into .env"
        return False

    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Test connection by querying batches table
        client.table("fetch_batches").select("id").limit(1).execute()
        status = "connected"
        status_msg = f"Connected to Supabase"
        return True
    except Exception as e:
        client = None
        status = "error"
        status_msg = f"Supabase error: {str(e)[:200]}"
        return False


def is_connected():
    return status == "connected" and client is not None


def _now():
    return datetime.now(timezone.utc).isoformat()


def _to_row(doc):
    """Strip internal fields before insert."""
    out = dict(doc)
    out.pop("_id", None)
    out.pop("id", None)
    return out


# ── BATCHES ──────────────────────────────────────────────────────────────────

def save_batch(batch_doc, student_docs):
    if not is_connected():
        return None, "Supabase not connected", False, 0
    try:
        # Check for existing batch with same key
        existing = client.table("fetch_batches").select("*").eq("year", batch_doc["year"]).eq("scheme", batch_doc["scheme"]).eq("semester", batch_doc["semester"]).eq("department", batch_doc["department"]).execute()
        rows = existing.data or []

        if not rows:
            # New batch
            insert_doc = _to_row(batch_doc)
            insert_doc["saved_at"] = _now()
            result = client.table("fetch_batches").insert(insert_doc).execute()
            batch_id = result.data[0]["id"]
            for s in student_docs:
                s["batch_id"] = batch_id
            if student_docs:
                s_rows = [_to_row(s) for s in student_docs]
                # Insert in chunks of 500
                for i in range(0, len(s_rows), 500):
                    client.table("student_results").insert(s_rows[i:i+500]).execute()
            return batch_id, len(student_docs), False, len(student_docs)

        # Merge path
        batch_id = rows[0]["id"]
        existing_res = client.table("student_results").select("usn").eq("batch_id", batch_id).execute()
        existing_usns = set(r["usn"] for r in (existing_res.data or []))
        new_docs = [d for d in student_docs if d["usn"] not in existing_usns]
        new_docs.sort(key=lambda d: d.get("usn", ""))
        if new_docs:
            s_rows = [{"batch_id": batch_id, **_to_row(s)} for s in new_docs]
            for i in range(0, len(s_rows), 500):
                client.table("student_results").insert(s_rows[i:i+500]).execute()

        total_res = client.table("student_results").select("id", count="exact").eq("batch_id", batch_id).execute()
        total = total_res.count or len(new_docs)
        merged_subjects = sorted(
            set(rows[0].get("subjects") or []) | set(batch_doc.get("subjects") or [])
        )
        client.table("fetch_batches").update({
            "student_count": total,
            "subjects": json.dumps(merged_subjects),
            "saved_at": _now(),
        }).eq("id", batch_id).execute()
        return batch_id, len(new_docs), True, total

    except Exception as e:
        return None, str(e), False, 0


def merge_into_batch(batch_id, batch_doc, student_docs):
    if not is_connected():
        return None, "Supabase not connected", False, 0
    try:
        existing = client.table("fetch_batches").select("*").eq("id", batch_id).execute()
        rows = existing.data or []
        if not rows:
            return None, "Batch not found", False, 0

        existing_res = client.table("student_results").select("usn").eq("batch_id", batch_id).execute()
        existing_usns = set(r["usn"] for r in (existing_res.data or []))
        new_docs = [d for d in student_docs if d["usn"] not in existing_usns]
        new_docs.sort(key=lambda d: d.get("usn", ""))
        if new_docs:
            s_rows = [{"batch_id": batch_id, **_to_row(s)} for s in new_docs]
            for i in range(0, len(s_rows), 500):
                client.table("student_results").insert(s_rows[i:i+500]).execute()

        total_res = client.table("student_results").select("id", count="exact").eq("batch_id", batch_id).execute()
        total = total_res.count or len(new_docs)
        merged_subjects = sorted(
            set(rows[0].get("subjects") or []) | set(batch_doc.get("subjects") or [])
        )
        client.table("fetch_batches").update({
            "student_count": total,
            "subjects": json.dumps(merged_subjects),
            "saved_at": _now(),
        }).eq("id", batch_id).execute()
        return batch_id, len(new_docs), True, total

    except Exception as e:
        return None, str(e), False, 0


def fetch_batches(limit=100):
    if not is_connected():
        return []
    try:
        result = client.table("fetch_batches").select("*").order("saved_at", desc=True).limit(limit).execute()
        rows = result.data or []
        for r in rows:
            if isinstance(r.get("subjects"), str):
                try:
                    r["subjects"] = json.loads(r["subjects"])
                except Exception:
                    r["subjects"] = []
            if isinstance(r.get("credits"), str):
                try:
                    r["credits"] = json.loads(r["credits"])
                except Exception:
                    r["credits"] = {}
        return rows
    except Exception as e:
        print(f"[Supabase] fetch_batches error: {e}")
        return []


def distinct_batch_values(field):
    if not is_connected():
        return []
    try:
        result = client.table("fetch_batches").select(field).execute()
        values = set()
        for r in (result.data or []):
            v = r.get(field)
            if v is not None and str(v).strip():
                values.add(str(v))
        return sorted(values)
    except Exception as e:
        print(f"[Supabase] distinct_batch_values error: {e}")
        return []


def fetch_batch(batch_id):
    if not is_connected():
        return None
    try:
        result = client.table("fetch_batches").select("*").eq("id", batch_id).execute()
        rows = result.data or []
        if not rows:
            return None
        r = rows[0]
        if isinstance(r.get("subjects"), str):
            try:
                r["subjects"] = json.loads(r["subjects"])
            except Exception:
                r["subjects"] = []
        if isinstance(r.get("credits"), str):
            try:
                r["credits"] = json.loads(r["credits"])
            except Exception:
                r["credits"] = {}
        return r
    except Exception as e:
        print(f"[Supabase] fetch_batch error: {e}")
        return None


def delete_batch(batch_id):
    if not is_connected():
        return False, "Supabase not connected"
    try:
        client.table("student_results").delete().eq("batch_id", batch_id).execute()
        result = client.table("fetch_batches").delete().eq("id", batch_id).execute()
        return True, None
    except Exception as e:
        return False, str(e)


# ── STUDENTS ─────────────────────────────────────────────────────────────────

def fetch_students(batch_id):
    if not is_connected():
        return []
    try:
        result = client.table("student_results").select("*").eq("batch_id", batch_id).order("usn").execute()
        rows = result.data or []
        for r in rows:
            if isinstance(r.get("subjects"), str):
                try:
                    r["subjects"] = json.loads(r["subjects"])
                except Exception:
                    r["subjects"] = []
        return rows
    except Exception as e:
        print(f"[Supabase] fetch_students error: {e}")
        return []


def fetch_student_record(usn):
    if not is_connected():
        return None
    try:
        usn = usn.strip().upper()
        students_res = client.table("student_results").select("*").eq("usn", usn).execute()
        students = students_res.data or []
        if not students:
            return None

        name = ""
        semesters = []
        seen_sem = set()
        for s in students:
            batch_id = s.get("batch_id", "")
            batch = fetch_batch(batch_id)
            if not batch:
                continue
            sem = batch.get("semester", "?")
            if sem in seen_sem:
                continue
            seen_sem.add(sem)
            if not name:
                name = s.get("name", "")
            subjects = s.get("subjects", []) or []
            if isinstance(subjects, str):
                subjects = json.loads(subjects)
            credits_map = batch.get("credits", {}) or {}
            if isinstance(credits_map, str):
                credits_map = json.loads(credits_map)
            if credits_map:
                for subj in subjects:
                    cr = credits_map.get(subj.get("code", ""))
                    if cr is not None:
                        subj["credit"] = float(cr)
            semesters.append({
                "batch_id": batch_id,
                "semester": sem,
                "scheme": batch.get("scheme", ""),
                "year": batch.get("year", ""),
                "department": batch.get("department", ""),
                "subjects": subjects,
                "percentage": s.get("percentage"),
                "result_status": s.get("result_status", ""),
                "saved_at": batch.get("saved_at", ""),
            })

        def sem_sort_key(x):
            try:
                return int(x.get("semester", 99))
            except (ValueError, TypeError):
                return 99
        semesters.sort(key=sem_sort_key)

        return {"usn": usn, "name": name, "semesters": semesters}
    except Exception as e:
        print(f"[Supabase] fetch_student_record error: {e}")
        return None


def fetch_batch_with_students(batch_id):
    batch = fetch_batch(batch_id)
    if batch is None:
        return None, None
    return batch, fetch_students(batch_id)


# ── CREDITS & SGPA ──────────────────────────────────────────────────────────

def save_credits(batch_id, credits_map):
    if not is_connected():
        return False, "Supabase not connected"
    try:
        client.table("fetch_batches").update({
            "credits": json.dumps(credits_map),
            "credits_updated_at": _now(),
        }).eq("id", batch_id).execute()
        return True, None
    except Exception as e:
        return False, str(e)


def get_credits(batch_id):
    if not is_connected():
        return {}
    try:
        result = client.table("fetch_batches").select("credits").eq("id", batch_id).execute()
        rows = result.data or []
        if not rows:
            return {}
        credits = rows[0].get("credits", {})
        if isinstance(credits, str):
            credits = json.loads(credits)
        return credits or {}
    except Exception:
        return {}


def compute_sgpa(students, credits_map):
    for s in students:
        total_credits = 0
        total_points = 0
        cgpa_credits = 0
        cgpa_points = 0
        subjects = s.get("subjects", []) or []
        if isinstance(subjects, str):
            subjects = json.loads(subjects)
        for subj in subjects:
            code = subj.get("code", "")
            cr = credits_map.get(code)
            if cr is None:
                continue
            try:
                cr = float(cr)
            except (TypeError, ValueError):
                continue
            grade = subj.get("final_grade") if subj.get("is_revaluated") and subj.get("final_grade") else subj.get("grade", "")
            if not grade:
                if subj.get("is_revaluated") and subj.get("final_total") is not None:
                    best_total = subj["final_total"]
                elif subj.get("is_revaluated") and subj.get("final_marks") is not None and subj.get("internal") is not None:
                    best_total = subj["internal"] + subj["final_marks"]
                else:
                    best_total = subj.get("total")
                grade = _grade(best_total) if best_total is not None else ""
            gp = GRADE_POINTS.get(grade, 0)
            total_credits += cr
            total_points += gp * cr
            if gp > 0:
                cgpa_credits += cr
                cgpa_points += gp * cr
        s["sgpa"] = round(total_points / total_credits, 2) if total_credits > 0 else None
        s["cgpa"] = round(cgpa_points / cgpa_credits, 2) if cgpa_credits > 0 else None
    return students


def _grade(marks):
    """Map total marks to a VTU grade."""
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


def update_student_result(batch_id, usn, name, subjects, result_status):
    """Replace a student's result data in a batch. Returns True on success."""
    if not is_connected():
        return False
    try:
        # Find existing student
        existing = client.table("student_results").select("id").eq("batch_id", batch_id).eq("usn", usn).execute()
        rows = existing.data or []
        if rows:
            # Update existing
            client.table("student_results").update({
                "name": name,
                "subjects": json.dumps(subjects),
                "result_status": result_status,
            }).eq("id", rows[0]["id"]).execute()
        else:
            # Insert new
            client.table("student_results").insert({
                "batch_id": batch_id,
                "usn": usn,
                "name": name,
                "subjects": json.dumps(subjects),
                "result_status": result_status,
            }).execute()
        return True
    except Exception as e:
        print(f"[Supabase] update_student_result error: {e}")
        return False


def update_student_result_reval(batch_id, usn, name, new_subjects, result_status):
    """Apply revaluation update: preserve original marks for reval'd subjects,
    keep non-reval'd subjects untouched.

    new_subjects should have ALL subjects. For subjects with reval data,
    include original_external/original_total/original_result/original_grade
    and is_revaluated=True. For non-reval'd subjects, include the original
    DB values unchanged.
    """
    if not is_connected():
        return False
    try:
        # Fetch current student from DB
        existing = client.table("student_results").select("id, subjects").eq("batch_id", batch_id).eq("usn", usn).execute()
        rows = existing.data or []
        if not rows:
            return False

        row_id = rows[0]["id"]
        old_subjects_raw = rows[0].get("subjects", [])
        if isinstance(old_subjects_raw, str):
            old_subjects_raw = json.loads(old_subjects_raw)

        # Build lookup of old subjects by code
        old_map = {s.get("code", ""): s for s in old_subjects_raw}

        merged_subjects = []
        for subj in new_subjects:
            code = subj.get("code", "")
            old_subj = old_map.get(code, {})
            is_reval = subj.get("is_revaluated", False)

            merged = dict(subj)

            if is_reval:
                # Preserve originals: use old DB values if not already set
                if not merged.get("original_external"):
                    merged["original_external"] = old_subj.get("original_external") or old_subj.get("external")
                if not merged.get("original_total"):
                    merged["original_total"] = old_subj.get("original_total") or old_subj.get("total")
                if not merged.get("original_result"):
                    merged["original_result"] = old_subj.get("original_result") or old_subj.get("result")
                if not merged.get("original_grade"):
                    merged["original_grade"] = old_subj.get("original_grade") or old_subj.get("grade")
                merged["is_revaluated"] = True
            else:
                # Non-reval'd: use new subject data (is_revaluated=False) but preserve DB-specific fields
                if old_subj:
                    merged["rv_marks"] = None
                    merged["rv_result"] = ""
                    merged["final_marks"] = None
                    merged["final_result"] = ""
                    merged["final_grade"] = ""
                    merged["is_revaluated"] = False

            merged_subjects.append(merged)

        client.table("student_results").update({
            "name": name,
            "subjects": json.dumps(merged_subjects),
            "result_status": result_status,
        }).eq("id", row_id).execute()
        return True
    except Exception as e:
        print(f"[Supabase] update_student_result_reval error: {e}")
        return False
