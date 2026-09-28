# VTU Bulk Result Fetcher — Web Dashboard

Fetch VTU exam results in bulk, solve the image CAPTCHA automatically with a trained deep-learning model, export a pivot Excel report, archive everything to a Supabase (PostgreSQL) database, and browse per-student records in a VTU-style layout.

**Authors:** **ABHISHEK** (Author 1) · **PALLAVI** (Author 2) · https://github.com/Abhirajp16/Result-1

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)
![Flask](https://img.shields.io/badge/Flask-Web%20Framework-lightgrey?style=for-the-badge&logo=flask)
![TensorFlow](https://img.shields.io/badge/TensorFlow-CAPTCHA%20Solver-orange?style=for-the-badge&logo=tensorflow)
![Selenium](https://img.shields.io/badge/Selenium-Automation-green?style=for-the-badge&logo=selenium)
![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white)

---

## 1. What this project does

1. **Reads a list of USNs** (generated from a prefix + range, or pasted/imported from `students.csv`).
2. **Opens Chrome with Selenium** and submits each USN on the VTU result portal.
3. **Solves the 6-character CAPTCHA** with a CNN + GRU + CTC TensorFlow model (`vtu_captcha_predictor.h5`) — no manual typing, up to 15 retries per USN.
4. **Scrapes** subject-wise marks (Internal / External / Total / Result / announced date) and writes:
   - `raw_results.csv` — one row per subject per student
   - `raw_summary.csv` — one row per student (total, percentage)
   - `vtu_results.xlsx` — final pivot report (one row per student, one column group per subject)
5. **Streams every log line to the browser in real time** over Socket.IO.
6. **Saves the fetch into Supabase** (`fetch_batches` + `student_results`) so results can be browsed, analysed, exported and compared later.
7. **Revaluation mode** re-fetches only revaluation results and merges them over the original marks (original values are preserved and shown struck-through).

---

## 2. Dashboard — 4 tabs

| Tab | What you can do |
| :--- | :--- |
| **Dashboard** | Build the USN list (prefix + From/To range generator, manual paste, Import CSV), set the VTU result URL, start/stop fetching, watch the live log, download the Excel, save the fetch to the database. |
| **Revaluation** | Pick a batch + USNs, run a reval fetch (`--reval`), compare old vs new marks, apply the reval result (auto: only if improved, or select subjects manually). |
| **Analytics** | Batch-wise rank cards (topper / average / lowest), percentage distribution chart, result-band pie chart (Distinction / First Class / Pass / Fail), subject-wise average marks. |
| **Browse Records** | Filter by Department / Semester / Scheme / Year, paginate through saved students, export a batch to Excel (`/export-batch/<batch_id>`). |

### Other pages

| URL | Purpose |
| :--- | :--- |
| `/` | Main dashboard |
| `/student-record` | Search one USN → full academic record (see section 6) |
| `/subject-analytics` | Subject-wise analytics |

---

## 3. Tech stack

| Layer | Technologies |
| :--- | :--- |
| Backend | Python, Flask, Flask-SocketIO (threading async mode) |
| Automation | Selenium 4, webdriver-manager, BeautifulSoup4, lxml |
| Machine learning | TensorFlow/Keras (CNN + bidirectional GRU + CTC), OpenCV, NumPy |
| Data | Pandas, OpenPyXL |
| Database | Supabase (PostgreSQL) via `supabase-py`, `python-dotenv` for `.env` |
| Frontend | HTML5, Tailwind (local file), Chart.js (local file), Socket.IO client (local file) |
| Browser | Google Chrome (ChromeDriver resolved automatically) |

---

## 4. Project structure

```text
Recaptcha/
├── app.py                     # Flask + Socket.IO server, save/merge logic, SGPA/CGPA, reval handlers
├── db.py                      # Supabase layer: batches, students, merge, credits, delete
├── bulk_fetcher_6.py          # Scraper worker (current version) — Selenium + CAPTCHA + Excel
├── bulk_fetcher*.py           # Older scraper versions (kept for reference)
├── fetch.py                   # CLI wrapper: python fetch.py <url> [usn1 usn2 ...]
├── captcha.py                 # Downloads ~2000 CAPTCHA images for labelling
├── train.py                   # Trains the CNN+GRU+CTC model
├── solve.py                   # Test the model on a single CAPTCHA image
├── vtu_auto.py, htmlsaver.py  # Older single-USN scripts
├── templates/
│   ├── index.html             # Dashboard (4 tabs)
│   ├── student_record.html    # VTU-style student record page
│   └── subject_analytics.html
├── static/                    # socket.io.min.js, tailwind.js, chart.umd.min.js
├── .env                       # SUPABASE_URL + SUPABASE_KEY  (never committed)
├── schema.sql                 # Table definitions for Supabase
├── requirements.txt
├── students.csv               # INPUT — USN list (header `USN`)
├── reval_students.csv         # INPUT — USNs for reval fetch
├── raw_results.csv            # INTERMEDIATE — per-subject rows (normal fetch)
├── raw_summary.csv            # INTERMEDIATE — per-student totals
├── raw_results_rv.csv         # INTERMEDIATE — reval fetch
├── vtu_results.xlsx           # OUTPUT — pivot report (download from the UI)
├── vtu_results_rv.xlsx        # OUTPUT — reval report
├── vtu_captcha_predictor.h5   # Trained CAPTCHA model used at runtime
└── vtu_captcha_model.h5       # Best training checkpoint
```

> `run_app.ps1` and `start_server.bat` are **legacy launchers with hardcoded paths from another machine** — update them or simply run `python app.py`.

---

## 5. Setup & run

### Prerequisites
- Python 3.10+ (project runs on 3.11)
- Google Chrome
- A Supabase project (optional — the app still runs without it, DB features just disable themselves)

### Install

```bash
cd Recaptcha
python -m pip install -r requirements.txt
```

### Configure the database (optional)

Create `.env` in `Recaptcha/`:

```env
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_KEY=<service_role or anon key>
```

Run `schema.sql` in the Supabase SQL Editor once (it creates `fetch_batches` and `student_results`).
If `.env` is missing/wrong, the header shows **"DB off"** and every DB action returns a clear error — nothing crashes.

### Start the server

```bash
python app.py
```

Then open **http://127.0.0.1:5000**

---

## 6. Usage

1. **Build the USN list** — enter prefix (`1GD24CS`) + From/To → *Generate*, or paste USNs, or *Import CSV*.
2. **Check the VTU URL** (default `https://results.vtu.ac.in/.../index.php`) and click **Start Fetching**.
   - Live log + progress counter + stopwatch; **Stop Fetching** aborts safely.
   - After every USN the CSVs are rewritten, so a crash never loses progress.
3. **Download Excel** — pivot report appears when the run finishes (freshness is verified by file mtime before the button shows).
4. **Save to Database** — pick year / scheme / semester / department (or merge into an existing batch). Re-saving now **merges** students: existing rows are updated instead of skipped, and subjects are unioned so nothing is lost.
5. **Student Record** — open `/student-record`, enter a USN.
6. **Analytics / Browse** — analyse or filter saved batches; export a batch to Excel.
7. **SGPA / CGPA** — enter credits per subject per batch (`save-credits`), then compute SGPA/CGPA (`compute-yearly-cgpa`).

### How the student record is laid out (VTU format)

Subjects are grouped by **the semester encoded in the subject code** (`BCS601 → 6`, `BCSL606 → 6`, `BMATS101 → 1`) and rendered exactly like the VTU result page:

```text
University Seat Number: 1GD24CS401
Student Name: CHANDUSHREE D S

Semester: 6
Subject Code | Subject Name | Internal Marks | External Marks | Total | Result | Announced / Updated on
BCS601       | CLOUD COMPUTING | 39 | 25 | 64 | P | 2026-06-30
...

BACKLOG / SUPPLEMENTARY EXAM — SEMESTER: 5
Subject Code | Subject Name | Internal Marks | External Marks | Total | Result | Announced / Updated on
BCS502       | COMPUTER NETWORKS | 40 | 20 | 60 | P | 2026-07-28
```

- **Current exam** subjects (subject semester == the semester block they were saved under) → the normal `Semester: N` table.
- **Backlog / supplementary** subjects (an older-semester subject appearing in a later exam) → a **separate** table with its own label, under the semester they belong to.
- Duplicate subject codes keep the **latest exam** result; revalued rows show old value struck through + the new value with an `RV` badge.

### Revaluation flow

1. **Revaluation tab** → select batch + USNs → *Start Reval Fetch* (writes `reval_students.csv`, runs `bulk_fetcher_6.py <url> <run_id> --reval --batch-id <id>`).
2. *Compare* shows old vs new marks (`compare-reval`).
3. *Apply* merges the reval into the DB (`update-reval-result`) — **auto mode only applies a subject if the new total is higher**; otherwise pick subjects manually. Original marks are preserved in `original_*` fields.

---

## 7. HTTP routes & Socket.IO events

### Routes

| Route | Description |
| :--- | :--- |
| `GET /` | Dashboard |
| `GET /student-record` | Student record page |
| `GET /subject-analytics` | Subject analytics page |
| `GET /download` | `vtu_results.xlsx` (served with `Cache-Control: no-store`) |
| `GET /export-batch/<batch_id>` | Rebuilds an Excel from DB data only |
| `GET /api/student-record/<usn>` | JSON record (semesters + subjects) |
| `GET /api/subject-analytics?batch_id=&subject=` | JSON analytics for one subject |
| `GET /api/filters/{semesters,schemes,years}` | Distinct filter values |

### Socket.IO events

| Direction | Event | Purpose |
| :--- | :--- | :--- |
| client → server | `import-csv` | Load `students.csv` into the textarea |
| client → server | `start-fetch` / `stop-fetch` | Start/stop the scraper subprocess |
| client → server | `get-db-status` | Supabase connection status |
| client → server | `save-to-db` | Save/merge the last fetch into the DB |
| client → server | `get-batches` / `get-batch-results` / `delete-batch` | Browse tab |
| client → server | `get-fetched-subjects` / `save-credits` / `get-credits` | SGPA/CGPA credits |
| client → server | `compute-yearly-cgpa` | CGPA over a semester pair (1-2, 3-4, 5-6) |
| client → server | `start-reval-fetch` / `compare-reval` / `update-reval-result` | Revaluation tab |
| server → client | `log-message`, `fetch-started`, `fetch-progress`, `fetch-complete`, `download-ready` | Live status |
| server → client | `save-to-db-complete`, `batch-results`, `credits-saved`, `reval-compare`, `reval-updated` | Results of each action |

---

## 8. Data flow

```text
students.csv ──► bulk_fetcher_6.py ──► Chrome/Selenium ──► VTU result site
                        │                    ▲
                        │        CAPTCHA screenshot → model.predict → CTC decode
                        ▼
        raw_results.csv + raw_summary.csv ──► vtu_results.xlsx (pivot)
                        │
                        ▼  Save to Database
        Supabase: fetch_batches ─┬─ student_results
                                 ├─ /student-record  (VTU layout, current vs backlog tables)
                                 ├─ Analytics tab
                                 └─ Browse tab + /export-batch/<id>
```

---

## 9. Troubleshooting

| Problem | Fix |
| :--- | :--- |
| `Error loading CAPTCHA model` | `vtu_captcha_predictor.h5` missing from the project folder |
| Chrome fails to start | Chrome not installed, or stale driver — let Selenium Manager re-download |
| Every USN fails | VTU changed the page structure/URL — update the URL and selectors in `bulk_fetcher_6.py` |
| `[Error] A fetch is already running` | Double-fetch guard — wait or click Stop |
| Port 5000 in use | `Get-NetTCPConnection -LocalPort 5000` → stop that PID |
| Download gives an old file | The server only emits `download-ready` after verifying the Excel mtime |
| `PermissionError` writing files | Close `vtu_results.xlsx` in Excel before re-running |
| DB badge shows "off" | `.env` missing/wrong, or Supabase unreachable |
| Student shows only backlog subjects | Their full result was never saved — fetch that USN again and **Save to DB** (saving now merges instead of skipping) |
| SGPA shows 0 | No credits entered for those subjects, or marks below 40 (grade point 0) |

---

## 10. Disclaimer

For **educational purposes only**. Automated scraping may violate the VTU website's Terms of Service — use delays, keep request volume low, and expect possible IP blocking. Only publicly queryable seat-number results are fetched; no credentials are involved.

---

## 11. Authors

| | Name | Reference |
| :--- | :--- | :--- |
| **Author 1** | ABHISHEK | https://github.com/Abhirajp16/Result-1 |
| **Author 2** | PALLAVI | https://github.com/Abhirajp16/Result-1 |

Repository: https://github.com/Abhirajp16/Result-1

---

## 12. More documentation

- `../PROJECT_DOCUMENTATION.md` — deep file-by-file walkthrough of the architecture (written for an earlier build; MongoDB sections are now Supabase).
