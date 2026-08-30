# VTU Bulk Result Fetcher + CAPTCHA Solver — Complete Documentation

> A bit-by-bit, in-depth explanation of how this project works, file by file, end to end.
> **v2 (2026 build):** stale-Excel bug fixed, SGPA removed, USN range generator added,
> MongoDB archive (Atlas), Analytics & Browse tabs, full light-theme redesign.
> See **Section 15 (v2 additions)** and **Section 16 (verified evidence)** below.

---

## 1. What Is This Project?

This is a **fully automated system** that fetches exam results from the **Visvesvaraya Technological University (VTU) result portal** for a *list of student USNs* (University Seat Numbers), automatically:

1. Solves the **image CAPTCHA** on the VTU website using a **trained Deep Learning model** (CNN + RNN + CTC, TensorFlow/Keras).
2. Fills the form (USN + CAPTCHA) and submits it using **Selenium** (automated Chrome browser).
3. **Scrapes** the result page HTML for subject-wise marks (Internal, External, Total, Result, Percentage).
4. Stores raw scraped data into intermediate CSV files.
5. Generates a **pivot-style Excel report** (`vtu_results.xlsx`) with one row per student and one column group per subject.
6. Optionally **archives every fetch into MongoDB** (`fetch_batches` + `student_results`) and provides **Analytics** and **Browse** tabs over the archived data.

Everything is driven from a **Flask + Flask-SocketIO web dashboard** (light theme, 3 tabs) that shows **real-time logs** while the bot works.

---

## 2. Big-Picture Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │              WEB BROWSER (User)              │
                    │  http://127.0.0.1:5000  (index.html)         │
                    │  - Enter USNs / Import CSV                   │
                    │  - Enter VTU URL                             │
                    │  - Watch live logs & progress                │
                    │  - Enter subject credits                     │
                    │  - Download vtu_results.xlsx                 │
                    └──────────────────┬───────────────────────────┘
                                       │  Socket.IO (WebSocket)
                                       ▼
                    ┌──────────────────────────────────────────────┐
                    │        FLASK BACKEND  (app.py)               │
                    │  Routes: / , /download                       │
                    │  Socket.IO events: import-csv, start-fetch,  │
                    │   stop-fetch, sgpa-credits, log-message,     │
                    │   fetch-progress, fetch-complete,            │
                    │   download-ready, fetch-started, csv-data    │
                    └──────────────────┬───────────────────────────┘
                                       │ spawns subprocess (Popen)
                                       ▼
                    ┌──────────────────────────────────────────────┐
                    │   SCRAPER  (bulk_fetcher_6.py)               │
                    │   1. Load CAPTCHA model (vtu_captcha_predictor.h5)
                    │   2. Open Chrome via Selenium + ChromeDriver │
                    │   3. For each USN: fill form, solve CAPTCHA, │
                    │      submit, handle alerts/retries, scrape   │
                    │   4. Write raw_results.csv / raw_summary.csv │
                    │   5. Build vtu_results.xlsx (pivot)          │
                    └──────────────────┬───────────────────────────┘
                                       │
                                       ▼
                    ┌──────────────────────────────────────────────┐
                    │            VTU RESULT WEBSITE                │
                    │  https://results.vtu.ac.in/JJEcbcs25/index.php│
                    └──────────────────────────────────────────────┘
```

### The three layers

| Layer | Files | Responsibility |
| :--- | :--- | :--- |
| **Frontend** | `templates/index.html`, `static/socket.io.min.js`, `static/tailwind.js` | UI, live log viewer, credit form, download button |
| **Backend server** | `app.py` | Flask web server, Socket.IO bridge, process manager, SGPA calculation |
| **Scraper worker** | `bulk_fetcher_6.py` | Selenium automation + ML CAPTCHA solving + HTML scraping + Excel generation |

---

## 3. Complete File-by-File Breakdown

### Root folder (`D:\abhi\vtu result fetch\`)

| File / Folder | Purpose |
| :--- | :--- |
| `Recaptcha/` | The actual project (cloned from https://github.com/Mayur-U/Recaptcha) |
| `link.txt` | Stores the GitHub repo link + clone command for the project |
| `angel/test.py` | Scratch file — just prints `"Hello AWS Local Environment"` (unrelated experiment) |
| `pi/test.py` | Scratch file — same test print (unrelated experiment) |
| `.gitignore` | Ignores venv folders, `__pycache__`, generated outputs (`vtu_results.xlsx`, CSVs, captcha pngs, `server_pid.txt`) |
| `.git/` | Git history: `e95281b first commit`, `a1b5e7d add USN validation and double-fetch guard` |

---

### `Recaptcha/` — main project folder

#### 🎯 Core runtime files

| File | Purpose |
| :--- | :--- |
| `app.py` | **Main Flask backend.** Web server + Socket.IO + subprocess manager + SGPA calculator |
| `bulk_fetcher_6.py` | **The scraper worker.** Selenium automation + CAPTCHA solving + scraping + Excel export (called as a subprocess with the VTU URL as argument) |
| `templates/index.html` | The single-page dashboard UI |
| `static/socket.io.min.js` | Socket.IO JavaScript client (enables real-time push to browser) |
| `static/tailwind.js` | TailwindCSS CDN-in-a-file for styling |
| `students.csv` | **Input** — list of USNs to fetch (header `USN` + one USN per line) |
| `raw_results.csv` | **Intermediate** — one row per subject per student (scraped data) |
| `raw_summary.csv` | **Intermediate** — one row per student with totals & percentage |
| `vtu_results.xlsx` | **Final output** — pivot report + SGPA column |
| `vtu_captcha_predictor.h5` | **Trained Keras model** (final prediction model, CNN+RNN+CTC) |
| `vtu_captcha_model.h5` | Older/best-checkpoint model saved during training |
| `server_pid.txt` | PID of the running Flask server (written by `run_app.ps1`) |
| `run_app.ps1` | PowerShell launcher — starts `app.py` with Python 3.10 and saves PID |
| `start_server.bat` | Batch launcher — starts `app.py` with Python 3.10 and pauses |
| `requirements.txt` | pip dependencies |
| `README.md` | Original project readme (setup + usage guide) |
| `result_page.html` | Saved HTML of a scraped result page (from an earlier test run) |
| `2a84u4.png`, `cap.png`, `captcha.png`, `captcha_screenshot.png`, `img_0002.png` | CAPTCHA image screenshots captured during testing |

#### 🧠 Machine-learning files (training & evaluation pipeline)

| File | Purpose |
| :--- | :--- |
| `captcha.py` | **Dataset downloader** — scrapes ~2000 raw CAPTCHA images from the VTU site into `captcha_dataset/` (for manual labeling) |
| `train.py` | **Model trainer** — loads labeled images, builds CNN+RNN+CTC architecture, trains with CTC loss, saves `vtu_captcha_predictor.h5` |
| `solve.py` | **Single-image tester** — loads model, predicts a CAPTCHA image, prints the answer + CER (Character Error Rate) if a true label is given |
| `vtu_auto.py` | **Older single-USN automation** — Selenium script that solves CAPTCHA for ONE USN from console input (predecessor of the bulk fetcher) |
| `htmlsaver.py` | **Older automation** — like `vtu_auto.py` but saves the result page HTML to `result_page.html` instead of scraping |

#### 📦 Old / experimental scraper versions (evolution of the code)

These are earlier iterations of the bulk fetcher, kept for reference. Each fixed bugs from the previous version:

| File | Notes on evolution |
| :--- | :--- |
| `bulk_fetcher.py` | First bulk version |
| `bulk_fetcher2.py` | Second iteration |
| `bulk_fetcher_4_excelfix.py` | Excel-generation fixes |
| `bulk_fetcher_5_excelfix.py` | More Excel fixes (pivot table) |
| `bulk_fetcher_6.py` | **CURRENT version used by app.py** — robust alert handling, safe refresh, stable CAPTCHA retry loop, URL argument support |

#### 🧪 Test files

| File | Purpose |
| :--- | :--- |
| `test_fetch.py` | Socket.IO client test — connects to the running server and triggers `start-fetch` with a fake USN |
| `test_socket.py` | Socket.IO client test — connects and emits `import-csv`, prints CSV data |
| `fetch.py` | CLI wrapper — runs `bulk_fetcher_6.py` from the command line: `python fetch.py <url> [usn1 usn2 ...]` |
| `test,py.txt` | Leftover scratch text file (broken `print` statement, not used) |
| `raw_results.csv`, `raw_summary.csv` | Present sample outputs from a previous real run |

---

## 4. The CAPTCHA-Solving Machine Learning Model

### 4.1 Why a model is needed

The VTU result site protects each form submission with a **6-character alphanumeric image CAPTCHA**. A human normally reads it and types it. This project trains a neural network to do that reading automatically.

### 4.2 Pipeline overview

```
captcha.py ──► 2000 raw PNGs ──► human labels them ──► train.py ──► vtu_captcha_predictor.h5
                                                                        │
                                                                        ▼
                                    In bulk_fetcher_6.py: screenshot → preprocess → model.predict → CTC decode → "4gH2k9"
```

### 4.3 `captcha.py` — dataset collection (step 1)

1. Uses a `requests.Session()` to keep cookies alive between requests.
2. Sets a browser-like `User-Agent` header.
3. Loops `IMAGES_TO_DOWNLOAD = 2000` times:
   - Loads the main page `https://results.vtu.ac.in/JJEcbcs25/index.php` (each load = fresh session = fresh CAPTCHA).
   - Uses `BeautifulSoup` to find the `<img>` tag whose `src` contains `vtu_captcha.php`.
   - Joins the relative URL with `BASE_URL = "https://results.vtu.ac.in/"` using `urljoin`.
   - Downloads the image **with the same session** and saves it as `captcha_dataset/img_XXXX.png`.
4. Uses `verify=False` to bypass SSL certificate issues (with `urllib3` warnings disabled).
5. A human then manually renames each file to its text, e.g. `4gH2k9.png`, to create labeled training data.

### 4.4 `train.py` — model training (step 2)

**Data preparation (`build_dataset` + `encode_labels`):**
- Reads every image file from `DATA_DIR = "archive/captchas/"` (point this to your labeled folder).
- The **filename** (minus extension) is the **label**, e.g. `4gH2k9.png` → label `4gH2k9`.
- Skips labels longer than `MAX_LENGTH = 6` or containing characters outside the 62-character set:
  `"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"`.

**Image preprocessing (must match runtime preprocessing exactly):**
1. Read as **grayscale** (`cv2.IMREAD_GRAYSCALE`).
2. `GaussianBlur` with kernel `(5,5)` — reduces noise.
3. **Otsu's binary inverse threshold** — makes the dark CAPTCHA text white and the light background (e.g. the "CAMPUS" watermark) black. This is the key cleaning step.
4. Resize to exactly **160 × 75** pixels.
5. Normalize pixel values to `[0, 1]` (divide by 255).
6. Add channel dimension → shape `(75, 160, 1)`.

**Label encoding:**
- Each label is encoded into a fixed-length numeric array of size `MAX_LENGTH = 6` using `char_to_num` mapping.
- Also builds the per-sample `label_length` array (needed by CTC loss).

**Model architecture — CNN + RNN + CTC:**

```
Inputs:
  image        (75, 160, 1)
  labels       (6,)          ─┐
  input_length (1,)           │  only used during training
  label_length (1,)          ─┘

CNN feature extractor:
  Conv2D(32, 3×3, relu, padding=same)  → (75, 160, 32)
  MaxPooling2D(2×2)                    → (37, 80, 32)
  Conv2D(64, 3×3, relu, padding=same)  → (37, 80, 64)
  MaxPooling2D(2×2)                    → (18, 40, 64)

Reshape to time-sequence for RNN:
  new_shape = (160 // 4, (75 // 4) * 64) = (40, 1152)
  → 40 timesteps (one per horizontal slice), 1152 features

  Dense(64, relu)  →  Dropout(0.2)

RNN (bidirectional, captures left-to-right character order):
  Bidirectional(GRU(128, return_sequences=True))
  Bidirectional(GRU(64,  return_sequences=True))

Output:
  Dense(62 + 1, softmax)   ← 62 characters + 1 CTC blank token
  Per timestep, probability over 63 classes.
```

**Why CTC (Connectionist Temporal Classification)?**
- The CAPTCHA characters are **variable length** (often 6, but sometimes fewer).
- CTC lets the model output a sequence at every timestep (40 timesteps) and then **collapses repeats + removes the blank token (−1)** to produce the final string. This avoids needing pixel-perfect character segmentation.

**Custom `CTCLayer`:** adds `tf.keras.backend.ctc_batch_cost` as a self-contained loss inside the model (the label arrays are passed in as inputs).

**Training setup:**
- 90% train / 10% validation split (`train_test_split`, `random_state=42`).
- `input_length` for every sample = `IMG_WIDTH // 4 = 40` timesteps.
- Optimizer `adam`, `epochs=100`, `batch_size=8`.
- `ModelCheckpoint` saves the best `vtu_captcha_model.h5` (monitors `val_loss`).
- `EarlyStopping` with patience 10, restoring best weights.
- The `fit` call uses `y = zeros(...)` because the loss is embedded in the model.

**Outputs:**
- `vtu_captcha_model.h5` — best training checkpoint.
- `vtu_captcha_predictor.h5` — the clean **prediction model** (image in → probability sequence out). This is the one used at runtime.

### 4.5 `solve.py` — test a single image (step 3)

- CLI: `python solve.py path/to/captcha.png [TrueLabel]`.
- Preprocesses the image identically to training.
- Loads `vtu_captcha_predictor.h5`, predicts, and decodes with `K.ctc_decode(..., greedy=True)`.
- Decoding: iterate output timesteps; `-1` is the CTC blank → stop; map each number back to a character via `num_to_char`.
- If a true label is supplied, prints **Exact Match** (yes/no) and **CER** (Character Error Rate via `editdistance` — lower is better).

---

## 5. The Scraper Worker — `bulk_fetcher_6.py` (bit-by-bit)

This is the heart of the system. It is **not run directly** by the user in normal operation — `app.py` launches it as a **subprocess** with the VTU URL as its first command-line argument.

### 5.1 Startup sequence

1. **Config:**
   - `VTU_RESULTS_URL = "https://results.vtu.ac.in/JJEcbcs25/index.php"` — overridden by `sys.argv[1]` if provided.
   - Model file `vtu_captcha_predictor.h5`, input `students.csv`, outputs `raw_results.csv`, `raw_summary.csv`, `vtu_results.xlsx`.
   - Image size 160×75, character set of 62, `MAX_ATTEMPTS = 15` retries per USN.
2. **Read USNs:** `pd.read_csv("students.csv")`, take the `USN` column, strip whitespace, convert to list.
3. **Load model:** `tf.keras.models.load_model("vtu_captcha_predictor.h5")`.
4. **Start Chrome:** `webdriver.Chrome(service=Service(ChromeDriverManager().install()))` — `webdriver-manager` automatically downloads the correct ChromeDriver matching your installed Chrome (no manual driver setup).

### 5.2 Helper functions

| Function | What it does |
| :--- | :--- |
| `preprocess(path)` | Grayscale → GaussianBlur(5×5) → Otsu inverse threshold → resize 160×75 → normalize → reshape to `(1, 75, 160, 1)` (adds batch dim for `predict`) |
| `decode(pred)` | CTC greedy decode; collects chars until blank token `-1`; caps output at 6 chars |
| `scrape(html)` | BeautifulSoup parsing (see 5.4) |
| `accept_alert_if_present(driver, timeout)` | Waits briefly for a JS alert; if found, prints its text and clicks **OK**; returns True/False |
| `safe_refresh(driver)` | Closes any alert first, then `driver.refresh()`; retries once if an `UnexpectedAlertPresentException` appears mid-refresh; tolerates transient `WebDriverException`s |

### 5.3 The per-USN fetch loop

For each USN (the outer `for usn in usns:` loop):

1. **Navigate** to the VTU results page (`driver.get(...)`). If this throws, do a `safe_refresh`.
2. Enter the **attempt loop** (up to `MAX_ATTEMPTS = 15`):
   - **Find form elements:**
     - USN input: `By.NAME, "lns"`
     - CAPTCHA input: `By.NAME, "captchacode"`
     - CAPTCHA image: XPath `//img[contains(@src,'vtu_captcha.php')]`
     - Submit button: `By.ID, "submit"`
   - **Clear** both text boxes (guarded with try/except).
   - **Type the USN** into the `lns` box.
   - **Screenshot the CAPTCHA element** to `cap.png` (`img.screenshot("cap.png")`).
   - **Predict:** `preprocess("cap.png")` → `model.predict(...)` → `decode(...)`.
   - **Validation:** if the predicted string is missing or not exactly 6 chars, `safe_refresh` and retry (a broken prediction is usually a blurry CAPTCHA).
   - **Type the CAPTCHA** into `captchacode` (with clear-and-retry fallback).
   - **Record `old_url`** (to detect page navigation later). If an alert blocks reading the URL, accept it and refresh.
   - **Click submit** (`btn.click()`). If an alert pops up during the click, accept → refresh → retry. If the click fails, fall back to a **JavaScript click** (`arguments[0].click()`); if even that fails, refresh and retry.
   - **Post-click alert check:** VTU shows a JavaScript alert ("Invalid CAPTCHA" etc.) when the CAPTCHA is wrong. If an alert is detected within 1s, accept it, refresh, and go to the next attempt.
   - **Wait for navigation:** `WebDriverWait(driver, 4).until(EC.url_changes(old_url))`.
     - `UnexpectedAlertPresentException` → accept alert, refresh, retry.
     - `TimeoutException` (URL didn't change → still on the form, CAPTCHA likely wrong) → check for alert once more, refresh, retry.
   - **Scrape the result page** (`driver.page_source` → `scrape(...)`):
     - On success: append subject rows + summary row to in-memory lists, mark `success = True`, print `[Success] Scraped <USN> - <Name> with N subjects.`, and `break` out of the attempt loop.
     - On any error: log, traceback, `safe_refresh`, retry.
   - **Global exception handlers** inside the loop catch `UnexpectedAlertPresentException`, `TimeoutException`, and generic `Exception` — always: accept alert → safe_refresh → sleep 0.5s → retry.
3. **If all attempts fail:** print `FAILED to fetch results for USN: <usn>` and append a placeholder summary row `{'USN': usn, 'Name': 'FETCH FAILED', 'percentage': 0, ...}` so the student still appears in the Excel file.
4. **Incremental saves:** after *every* USN, both intermediate CSVs are rewritten — so a crash or manual stop never loses already-fetched data (partial progress preserved).

### 5.4 `scrape()` — parsing the result HTML

The VTU result page layout (parsed with BeautifulSoup):

1. **Student identity** — first two rows of `<table class="table-condensed">`:
   - Row 0 → USN (2nd `<td>`, colons stripped).
   - Row 1 → Student Name.
   - If anything is missing → `("UNKNOWN", "UNKNOWN")` fallback.
2. **Subject table** — `<div class="divTableBody">` containing many `<div class="divTableRow">` rows, each with 7 `<div class="divTableCell">` cells:
   - `c[0]` = Subject Code
   - `c[1]` = Subject Name
   - `c[2]` = Internal Marks
   - `c[3]` = External Marks
   - `c[4]` = Total Marks
   - `c[5]` = Result (`P`/`F`)
   - `c[6]` = "Announced / Updated on" date
   - Rows with fewer than 7 cells or the header row (contains "Subject Code") are skipped.
3. **Totals:** every subject adds 100 to `max_total`; `total` sums the Total Marks; `percentage = total / max_total * 100`.
4. Returns `((usn, name), subject_rows, summary_dict)`.

### 5.5 Excel generation (final phase)

1. Read both CSVs; `drop_duplicates()` on subject rows and on USN for the summary (keep last).
2. Build a **pivot table**:
   - `index = ["USN", "Name"]`
   - `columns = "Subject Code"`
   - `values = ["Internal Marks", "External Marks", "Total Marks", "Result"]`
   - `aggfunc = "first"`
3. Flatten the multi-level column names: `f"{c2} - {c1}"` e.g. `"BCS401 - Internal Marks"`.
4. Format `Percentage` as `"89.00%"`; rename `total_obtained → "Overall Total"`, `total_max → "Overall Max Marks"`.
5. **Outer merge** pivot with summary on `["USN", "Name"]` (keeps even students with zero subjects).
6. Save to `vtu_results.xlsx` — **SGPA is NOT computed here**; that is done by `app.py` later.
7. Print `[SUBJECTS]:code1,code2,...` — this line is what unlocks the credit form in the web UI.

### 5.6 Robustness techniques used

- **Alert zombie handling:** VTU pages throw JavaScript `alert()` dialogs for "invalid CAPTCHA". Every risky operation is wrapped so dialogs get accepted first, never left hanging (a hanging alert freezes the whole browser).
- **URL-change detection** as success signal instead of guessing page content.
- **JavaScript click fallback** when normal clicks are intercepted.
- **15 attempts** with refreshing — each refresh yields a new CAPTCHA image.
- **Partial saves** after every USN.

---

## 6. The Web Backend — `app.py` (bit-by-bit)

### 6.1 Globals & setup

- Paths: `BACKEND_SCRIPT = bulk_fetcher_6.py`, `DEFAULT_CSV = students.csv`, `RAW_DATA = raw_results.csv`, `OUTPUT_EXCEL = vtu_results.xlsx`.
- `USN_PATTERN = ^[A-Z0-9]{10}$` — server-side USN validation.
- `current_process` — reference to the running scraper subprocess (prevents double-fetch).
- `fetch_stats = {"total": 0, "success": 0, "fail": 0}` — progress counters.
- Flask app with `SocketIO(app, async_mode="threading", cors_allowed_origins="*")`.

### 6.2 HTTP routes

| Route | Method | Action |
| :--- | :--- | :--- |
| `/` | GET | Renders `index.html` (the dashboard) |
| `/download` | GET | Streams `vtu_results.xlsx` as an attachment; 404 if the file doesn't exist yet |

### 6.3 Socket.IO events (server side)

| Event (client → server) | What it does |
| :--- | :--- |
| `import-csv` | Reads `students.csv`, **skips the header line** (`readlines()[1:]`), emits `csv-data` with the USN text (fills the textarea) and a log line with the count. Errors if file missing. |
| `start-fetch` | Receives `{usns: [...], url: "..."}`. Validates: no already-running process (double-fetch guard), non-empty USNs, non-empty URL. **Validates each USN** against the regex (strips/uppercases; invalid ones are logged as skipped). Writes the cleaned list back into `students.csv`. Initializes `fetch_stats`. Spawns `run_scraper` as a **background thread** (so the event handler returns instantly), emits `fetch-started {total}`. |
| `stop-fetch` | If a process is running, `current_process.terminate()` and log `[Stopped]`. |
| `sgpa-credits` | Receives `{credits: {subject_code: int}}`. Reads `raw_results.csv`, computes SGPA per USN, adds an `SGPA` column to the Excel, saves, emits log + `download-ready`. (Full formula in section 7.) |

### 6.4 `run_scraper(vtu_url, total_usns)` — the bridge

1. Builds `cmd = [sys.executable, "bulk_fetcher_6.py", vtu_url]`.
2. `subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True, cwd=BASE_DIR)` — **every line the scraper prints is both stdout and stderr combined**, so nothing is lost.
3. **Streams logs live:** loops over `process.stdout.readline()` and emits each line to the browser via `socketio.emit("log-message", ...)`.
4. **Tracks progress:** if a line contains `[Success] Scraped` → increment `success`; if it contains `FAILED to fetch` → increment `fail`; then emit `fetch-progress` with the stats dict (drives the `n/total` counter in the UI).
5. On process exit: clears `current_process`, emits `fetch-complete` with final stats, and if the Excel exists emits `download-ready` (shows the Download button).

### 6.5 SGPA math — `marks_to_gp()` + `sgpa_calc()`

VTU grade-point table (absolute grading):

| Total Marks | Grade Point |
| :--- | :--- |
| 90 – 100 | 10 |
| 80 – 89 | 9 |
| 70 – 79 | 8 |
| 60 – 69 | 7 |
| 50 – 59 | 6 |
| 45 – 49 | 5 |
| 40 – 44 | 4 |
| < 40 | 0 |

`marks_to_gp(m)` converts a mark to its point (non-numeric → 0).

`sgpa_calc` for **each USN**:
```
total_points = Σ (grade_point × credit)  over subjects that have credits entered
total_credits = Σ credits
SGPA = round(total_points / total_credits, 2)   (0 if total_credits is 0)
```

Subjects with no credit entered are **skipped** (not counted as 0) — so the user must enter credits for every subject they want counted.

Finally: `excel["SGPA"] = excel["USN"].apply(lambda u: sgpa_map.get(u, 0))` → save → emit `download-ready`.

### 6.6 Server startup

```python
socketio.run(app, host="127.0.0.1", port=5000, allow_unsafe_werkzeug=True, use_reloader=False)
```

- Binds to `127.0.0.1:5000` only (local machine).
- `use_reloader=False` is critical — the reloader would double-spawn and confuse the subprocess manager.

---

## 7. The Frontend — `templates/index.html` (bit-by-bit)

### Layout

1. **URL input** (`#vtu_url`) — pre-filled with the default VTU URL; user can change it if VTU releases a new results portal.
2. **USN textarea** (`#usn_text`) — comma- or newline-separated USNs.
3. **Buttons:**
   - `Import CSV` → emits `import-csv` (loads `students.csv` into the textarea).
   - `Start Fetching` → validates & emits `start-fetch`.
   - `Download Excel` → hidden until `download-ready`; navigates to `/download`.
4. **Status bar** (`#status_bar`, hidden until a fetch starts):
   - **Timer** — a live `mm:ss` stopwatch started on `fetch-started`.
   - **Progress** — `done/total` counter updated by `fetch-progress`.
   - **Stop Fetching** button → emits `stop-fetch`, disables itself, shows "Stopping…".
5. **Log output** (`#log`) — a `<pre>` block that appends every `log-message` and auto-scrolls to the bottom.
6. **SGPA panel** (`#sgpa_panel`, hidden until subjects arrive) — one credit number input per subject + `Calculate SGPA & Update Excel` button.

### JavaScript logic

- `logMsg(msg)` — appends to the log and keeps it scrolled to bottom.
- `USN_PATTERN = /^[A-Z0-9]{10}$/` — same validation as the server (client-side check).
- `validateUSNs(raw)` — splits on commas/newlines, trims, uppercases, filters empties; returns `{valid, invalid}`.
- `buildCreditUI()` — builds one credit `<input type="number" min=0 max=10>` per unique subject code, then shows the panel.
- **Socket.IO listeners:**
  - `log-message` → append to log; if the line starts with `[SUBJECTS]:` → parse the comma list, add to `allSubjects` set, and call `buildCreditUI()` (this is how the SGPA form unlocks automatically).
  - `csv-data` → fill the textarea.
  - `fetch-started` → show status bar, reset timer & counter, hide Start/Download, show Stop.
  - `fetch-progress` → update `done/total`.
  - `fetch-complete` → stop timer, restore Start button, log completion.
  - `download-ready` → show the Download button.
- **Button handlers** as described above; Start button clears the log and hides Download before emitting.

---

## 8. End-to-End Workflow (the full journey, step by step)

### Phase A — Server startup
1. User runs `python app.py` (or `run_app.ps1` / `start_server.bat`).
2. Flask + Socket.IO start on `http://127.0.0.1:5000`.
3. User opens the URL in Chrome → `index.html` loads.

### Phase B — Preparation
4. User types USNs (or clicks **Import CSV** → `import-csv` event → server reads `students.csv` (skipping the header) → returns `csv-data` → textarea is filled).
5. User confirms/changes the VTU URL.
6. User clicks **Start Fetching**.
   - Client validates USNs (regex) → shows warnings for invalid ones.
   - Sends `start-fetch {usns, url}` over WebSocket.

### Phase C — Server dispatch
7. `app.py` re-validates, filters, and **overwrites `students.csv`** with the validated list.
8. Spawns a background thread → `subprocess.Popen(["python", "bulk_fetcher_6.py", url])`.
9. Emits `fetch-started {total}` → UI shows status bar, timer starts.

### Phase D — Scraping loop (for each USN)
10. Scraper loads the trained CAPTCHA model + opens Chrome.
11. For each USN:
    - Load results page → find form fields.
    - Screenshot CAPTCHA → preprocess → predict → CTC decode → 6-char text.
    - If prediction invalid → refresh → new CAPTCHA → retry (up to 15×).
    - Type USN + CAPTCHA → click submit → wait for URL change.
    - Wrong CAPTCHA (JS alert) → accept → refresh → retry.
    - Success → parse HTML → collect subject rows + summary.
12. Every stdout line is forwarded to the browser log in real time; `[Success] Scraped ...` / `FAILED to fetch ...` lines update the progress counter.
13. After each USN, `raw_results.csv` and `raw_summary.csv` are rewritten (partial progress safety).

### Phase E — Excel generation
14. After the last USN, scraper builds the pivot Excel (`vtu_results.xlsx`) and prints the `[SUBJECTS]:` line.
15. Process exits → `app.py` emits `fetch-complete` (timer stops) and `download-ready` (Download button appears).

### Phase F — SGPA calculation
16. The `[SUBJECTS]:` line already unlocked the SGPA panel.
17. User enters credits per subject → clicks **Calculate SGPA & Update Excel** → `sgpa-credits` event → server computes SGPA per USN → writes `SGPA` column into the Excel → emits `download-ready`.

### Phase G — Download
18. User clicks **Download Excel** → browser hits `/download` → gets `vtu_results.xlsx` (raw marks + percentages + SGPA).

---

## 9. Data File Flow Diagram

```
students.csv (input USNs)
      │  read by bulk_fetcher_6.py
      ▼
[ Chrome (Selenium) ⇄ VTU Website ]
      │  scraped rows
      ▼
raw_results.csv ──┐            ┌──► vtu_results.xlsx (pivot: subject cols + totals)
raw_summary.csv ──┴─► merge ───┤           ▲
                               │           │ SGPA column added by app.py
                               └───────────┘  (uses raw_results.csv + credits)
```

---

## 10. How to Run the Project

### Option 1 — Recommended (PowerShell / cmd)

```powershell
cd "D:\abhi\vtu result fetch\Recaptcha"
C:\Users\Rajesh\AppData\Local\Programs\Python\Python310\python.exe app.py
```

Then open **http://127.0.0.1:5000** in Chrome.

### Option 2 — Launcher scripts

- `run_app.ps1` — starts `app.py`, writes the PID to `server_pid.txt`, waits for exit.
- `start_server.bat` — starts `app.py` and pauses so the window stays open.

### Option 3 — Just the scraper (no web UI)

```powershell
python fetch.py https://results.vtu.ac.in/JJEcbcs25/index.php 1GD23CS001 1GD23CS002
# or read USNs from students.csv:
python fetch.py https://results.vtu.ac.in/JJEcbcs25/index.php
```

### Note on the environment

- All dependencies are installed in the system Python 3.10 (`C:\Users\Rajesh\AppData\Local\Programs\Python\Python310\python.exe`): Flask 3.1.3, Flask-SocketIO 5.6.1, eventlet, tensorflow 2.21.0, selenium 4.46.0, webdriver-manager, pandas, opencv, openpyxl, bs4, lxml, scikit-learn.
- The README mentions a `tfenv` virtual env — it is **not present** in this machine; use the system Python 3.10 above.
- **ChromeDriver is automatic** — `webdriver-manager` downloads the matching driver for your installed Chrome on first run (no manual install needed).

---

## 11. Live Status (current run)

- Flask server is running on **http://127.0.0.1:5000** (PID 21844) — verified `HTTP 200` on `/`.
- To stop it: `Stop-Process -Id 21844` (or read `Recaptcha\server_pid.txt`).

---

## 12. Troubleshooting

| Problem | Likely cause / fix |
| :--- | :--- |
| `Error loading CAPTCHA model` | `vtu_captcha_predictor.h5` missing/moved from the project folder |
| Chrome fails to start | Chrome not installed; delete cached driver and let webdriver-manager re-download |
| Every USN fails | VTU changed page structure or blocked the bot (CAPTCHA/anti-bot). Update the URL/selectors in `bulk_fetcher_6.py` |
| `[Error] A fetch is already running` | Double-fetch guard active — wait for it to finish or click Stop |
| Port 5000 already in use | Old server instance still alive — kill it (`Get-NetTCPConnection -LocalPort 5000`) |
| SGPA shows 0 | Credits not entered for subjects, or marks below 40 (grade point 0) |
| Download 404 | Excel not generated yet — wait for `download-ready` |
| `PermissionError` writing files | Close `vtu_results.xlsx` in Excel before re-running |

---

## 13. Security & Ethics Disclaimer

- This project is for **educational purposes only**.
- Automated scraping may violate the **VTU website's Terms of Service**.
- Use responsibly: add delays, don't hammer the server, expect possible IP blocking.
- Credentials are not involved — only publicly queryable seat-number results are fetched.

---

## 14. Project Evolution (git history & file lineage)

```
e95281b  first commit                       ← initial upload
a1b5e7d  add USN validation and double-fetch guard
         (client + server USN regex, start-fetch guard)

bulk_fetcher.py        (v1 - basic)
  └─► bulk_fetcher2.py (v2 - fixes)
       └─► bulk_fetcher_4_excelfix.py (v3 - Excel pivot)
            └─► bulk_fetcher_5_excelfix.py (v4 - more Excel fixes)
                 └─► bulk_fetcher_6.py  (v5 - CURRENT: robust alerts/refresh)

htmlsaver.py → vtu_auto.py → bulk_fetcher_*.py   (single-USN → bulk)
```

---

## 15. v2 (2026 build) — what changed

### 15.1 New / modified files

| File | Change |
| :--- | :--- |
| `Recaptcha/.env` | **NEW** — `MONGODB_URI` + `MONGODB_DB_NAME` (user must paste rotated Atlas password; never committed — in `.gitignore`) |
| `Recaptcha/db.py` | **NEW** — MongoDB layer: `.env` loading, connection health-check, `insert_batch`, `fetch_batches`, `fetch_batch`, `fetch_students`, `fetch_batch_with_students`. Graceful degradation (app keeps working if Mongo is off) |
| `Recaptcha/app.py` | **REWRITTEN** — SGPA removed; run ID per fetch; `/download` cache-control; mtime verification before `download-ready`; `get-db-status`, `save-to-db`, `get-batches`, `get-batch-results` events; `/export-batch/<id>` REST route; `build_db_payload()` |
| `Recaptcha/templates/index.html` | **REWRITTEN** — 3 tabs (Dashboard / Analytics / Browse Records), light theme, USN range generator + manual add + combined preview, Save-to-DB modal, Chart.js charts, paginated browse table |
| `Recaptcha/static/chart.umd.min.js` | **NEW** — Chart.js 4.4.1 (local copy, matches the CDN-in-static pattern) |
| `Recaptcha/bulk_fetcher_6.py` | Accepts `run_id` as `argv[2]`, prints it with `[SUBJECTS]:`; browser auto-restart on crash; 0-subject retry + `debug_page.html` dump; USN cleanup (no leading spaces); fallback HTML-table parser |
| `Recaptcha/requirements.txt` | + `pymongo`, `python-dotenv` |

### 15.2 Stale-Excel fix (Phase 1) — root cause & fixes

Three causes were checked; the actual bugs found:

1. **`/download` had no cache-control headers** → browsers could serve a cached copy of the same-named file. Fixed with
   `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` + `conditional=False`.
2. **Old outputs were never cleared at fetch start** → previous run's `raw_results.csv` / `raw_summary.csv` / `vtu_results.xlsx` could be merged into (or remain as) the new report. Fixed by deleting all three at `start-fetch` (app.py) **and** at the start of `bulk_fetcher_6.main()`.
3. **`download-ready` was emitted even if the Excel was never rewritten** → now `app.py` compares `os.path.getmtime(vtu_results.xlsx)` against the fetch start time and only emits `download-ready` if the file was **verified fresh**; otherwise it logs a clear error.

Plus a **run ID** (`YYYYMMDD-HHMMSS`): logged at fetch start, passed to the scraper, printed with `[SUBJECTS]: ... (run <id>)`, and used in the "Excel verified fresh" log — so the user can always see which run produced which Excel.

### 15.3 MongoDB integration (Phase 4)

- Two collections in the `vtu_results` DB:
  - `fetch_batches` — `{year, scheme, semester, department, saved_at, usn_prefix, student_count, subjects[], run_id}`
  - `student_results` — `{batch_id, usn, name, subjects[{code, subject_name, internal, external, total, result}], percentage, result_status}`
- `save-to-db` event: validates fields → `build_db_payload()` reads the just-fetched `raw_results.csv`/`raw_summary.csv` → inserts batch + N students → emits `save-to-db-complete`.
- `get-batches` / `get-batch-results` feed the Analytics & Browse tabs.
- `/export-batch/<batch_id>` rebuilds an Excel from **DB data only** (independent of the live file).
- If Mongo is unreachable the UI badge shows "MongoDB off" and every DB feature returns a clear log error — nothing crashes.

### 15.4 USN input redesign (Phase 3)

- **Range generator:** prefix (e.g. `1GD24CS`) + From/To (zero-padded to 3 digits) → merges into the working list.
- **Manual add:** paste comma/newline-separated USNs (any dept/prefix) → merged, deduplicated.
- **Combined preview:** chip list with per-chip remove, live count, invalid entries flagged inline. Server re-validates on `start-fetch`.

### 15.5 Analytics tab (Phase 5)

- Batch dropdown (`"{department} — Sem {semester} — {scheme} — {year} ({student_count} students)"`).
- Rank cards: Top scorer, Batch average, Lowest (by percentage).
- Bar chart: percentage distribution across the batch.
- Pie chart: result bands — Distinction ≥70 / First Class ≥60 / Pass ≥40 / Fail <40.
- Bar chart: subject-wise average total marks.

### 15.6 Browse Records tab (Phase 6)

- Filter bar (Department / Semester / Scheme / Year) populated from distinct batch values.
- Paginated table (20/page): USN, Name, per-subject totals, %, PASS/FAIL pill.
- "Export to Excel" → `/export-batch/<batch_id>` for the first batch matching the filters.

### 15.7 UI redesign (Phase 7)

- Light theme, single teal accent, neutral gray scale, semantic green/red only.
- Persistent header with tabs; consistent spacing; sticky table headers, zebra rows, right-aligned numerics; custom-styled inputs/buttons with focus/disabled states; responsive charts.

---

## 16. v2 — verified evidence (all run and confirmed)

| Item | Evidence |
| :--- | :--- |
| Stale Excel fix | 2 consecutive real fetches: run `20260805-203702` (5 USNs) → download contained exactly 5 USNs; run `20260805-203807` (2 USNs) → download contained **exactly** `[1GD23CS002, 1GD23CS005]`, no leak |
| Download headers | `HTTP 200`, `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` |
| Fresh-file verification | `[Run <id>] Excel verified fresh (mtime …)` in logs before `download-ready` |
| Run ID | `[Run 20260805-203702] Fetch started …` / `[SUBJECTS]:… (run 20260805-203702)` |
| USN generator | node-based DOM test: generate `1GD24CS001..010` → re-generate dedupes to 10 → add `1GD24EC011, 1GD24EC012` + invalid → `start-fetch` payload = **exactly 12 valid USNs**, invalid flagged inline — ALL PASS |
| DB pipeline | `build_db_payload()` on real CSVs → 2 students, 9 subjects, correct `result_status`; in-memory Mongo stub: `insert_batch` → `fetch_batches` → `fetch_batch_with_students` → real `GET /export-batch/<id>` returned HTTP 200 Excel with the exact USNs — PASS |
| Graceful degradation | With `.env` placeholder: `db-status {connected:false}`, `get-batches` returns `error`, `save-to-db` logs `[DB ERROR] MongoDB not available` — no crash |
| Python/JS syntax | `py_compile` OK (app.py, db.py, bulk_fetcher_6.py); `node --check` OK (index.html inline JS) |
| Live server | `http://127.0.0.1:5000` HTTP 200; real fetch of 5 USNs through the UI pipeline: 5/5 scraped, Excel updated live |

**Remaining manual step:** paste the rotated Atlas password into `Recaptcha/.env` (the `MONGODB_URI` there currently has the placeholder `PASTE_ROTATED_PASSWORD_HERE`). Then the "Save to Database" button will write real batches to Atlas.
