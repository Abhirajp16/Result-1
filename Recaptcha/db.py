"""MongoDB persistence layer for the VTU result fetcher.

Reads MONGODB_URI / MONGODB_DB_NAME from the .env file (python-dotenv).
If MongoDB is not configured or unreachable, every function degrades
gracefully (returns empty results / error messages) — the app keeps working.
"""

import os
import threading
import time
from datetime import datetime

try:
    from dotenv import load_dotenv
    _dir = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_dir, ".env"))
except Exception:
    pass

from pymongo import MongoClient
from pymongo.errors import PyMongoError
from bson import ObjectId

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "vtu_results")

client = None
db = None
status = "disabled"
status_msg = "MongoDB not configured (set MONGODB_URI in .env)"

# Markers that mean the user hasn't filled in the real connection string yet
_PLACEHOLDER_MARKERS = ("PASTE_ROTATED_PASSWORD_HERE", "<db_password>", "<password>", "<username>", "<user>")


def init_db():
    """Try to connect to MongoDB. Never raises — logs status via return value."""
    global client, db, status, status_msg

    if not MONGODB_URI or any(m in MONGODB_URI for m in _PLACEHOLDER_MARKERS):
        status = "disabled"
        status_msg = "MongoDB not configured — paste your real MONGODB_URI into .env"
        return False

    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[MONGODB_DB_NAME]
        status = "connected"
        status_msg = f"Connected to MongoDB: {MONGODB_DB_NAME}"
        global _keepalive_running
        if not _keepalive_running:
            _keepalive_running = True
            t = threading.Thread(target=_keepalive_ping, daemon=True)
            t.start()
        return True
    except PyMongoError as e:
        client = None
        db = None
        status = "error"
        msg = str(e)
        if "tls" in msg.lower() or "ssl" in msg.lower():
            status_msg = (
                "MongoDB TLS handshake failed. This usually means your Atlas cluster is "
                "PAUSED or the network blocks port 27017. Open Atlas console, make sure "
                "the cluster shows 'Active', and try again."
            )
        else:
            status_msg = f"MongoDB unreachable: {msg[:200]}"
        return False


_keepalive_running = False

def _keepalive_ping():
    """Ping MongoDB every 5 minutes to prevent Atlas free tier from pausing."""
    global client, db, status, status_msg
    while True:
        time.sleep(300)
        if status == "connected" and client:
            try:
                client.admin.command("ping")
            except Exception:
                try:
                    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
                    client.admin.command("ping")
                    db = client[MONGODB_DB_NAME]
                    status = "connected"
                    status_msg = f"Connected to MongoDB: {MONGODB_DB_NAME}"
                except Exception:
                    status = "error"
                    status_msg = "MongoDB connection lost"
        else:
            try:
                client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
                client.admin.command("ping")
                db = client[MONGODB_DB_NAME]
                status = "connected"
                status_msg = f"Connected to MongoDB: {MONGODB_DB_NAME}"
            except Exception:
                pass


def is_connected():
    if status == "connected" and client is not None and db is not None:
        return True
    _auto_reconnect()
    return status == "connected" and client is not None and db is not None


def _auto_reconnect():
    """Try to reconnect if disconnected."""
    global client, db, status, status_msg
    if status == "connected":
        return
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=8000)
        client.admin.command("ping")
        db = client[MONGODB_DB_NAME]
        status = "connected"
        status_msg = f"Connected to MongoDB: {MONGODB_DB_NAME}"
    except Exception:
        pass


def _batches_coll():
    return db["fetch_batches"] if db is not None else None


def _students_coll():
    return db["student_results"] if db is not None else None


def _jsonable(doc):
    """Convert a Mongo doc into a JSON-safe dict (ObjectId/date -> str)."""
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    if isinstance(out.get("saved_at"), datetime):
        out["saved_at"] = out["saved_at"].isoformat()
    if "batch_id" in out:
        out["batch_id"] = str(out["batch_id"])
    return out


def insert_batch(batch_doc, student_docs):
    """Insert one fetch_batches doc + N student_results docs (same batch_id).
    Returns (batch_id_str, inserted_student_count) or (None, error_msg)."""
    if not is_connected():
        return None, "MongoDB not connected"
    try:
        batch_id = _batches_coll().insert_one(batch_doc).inserted_id
        for s in student_docs:
            s["batch_id"] = batch_id
        if student_docs:
            _students_coll().insert_many(student_docs)
        return str(batch_id), len(student_docs)
    except PyMongoError as e:
        return None, str(e)


def save_batch(batch_doc, student_docs):
    """Insert a new batch, or MERGE into an existing batch with the same
    (year, scheme, semester, department, result_type) — never creates a
    duplicate record. Only USNs not already present in that batch are appended.
    Returns (batch_id_str, added_count, was_merged, total_students)
    or (None, error_msg, False, 0)."""
    if not is_connected():
        return None, "MongoDB not connected", False, 0
    try:
        rtype = batch_doc.get("result_type", "original")
        existing = _batches_coll().find_one({
            "year": batch_doc["year"],
            "scheme": batch_doc["scheme"],
            "semester": batch_doc["semester"],
            "department": batch_doc["department"],
            "result_type": rtype,
        })

        if existing is None:
            batch_id = _batches_coll().insert_one(batch_doc).inserted_id
            for s in student_docs:
                s["batch_id"] = batch_id
            if student_docs:
                _students_coll().insert_many(student_docs)
            return str(batch_id), len(student_docs), False, len(student_docs)

        # ---- merge path: same batch already exists ----
        oid = existing["_id"]
        existing_usns = set(
            s["usn"] for s in _students_coll().find({"batch_id": oid}, {"usn": 1})
        )
        new_docs = [d for d in student_docs if d["usn"] not in existing_usns]
        new_docs.sort(key=lambda d: d.get("usn", ""))
        for s in new_docs:
            s["batch_id"] = oid
        if new_docs:
            _students_coll().insert_many(new_docs)

        total = _students_coll().count_documents({"batch_id": oid})
        merged_subjects = sorted(
            set(existing.get("subjects") or []) | set(batch_doc.get("subjects") or [])
        )
        _batches_coll().update_one(
            {"_id": oid},
            {"$set": {
                "student_count": total,
                "subjects": merged_subjects,
                "saved_at": datetime.utcnow(),
            }},
        )
        return str(oid), len(new_docs), True, total
    except PyMongoError as e:
        return None, str(e), False, 0


def merge_into_batch(batch_id, batch_doc, student_docs):
    """Merge students into ONE specific existing batch chosen by the user.

    Like save_batch's merge path, but the target batch is picked explicitly
    (by _id) instead of auto-matched on (year, scheme, semester, department).
    Only USNs not already present in that batch are appended.
    Returns (batch_id_str, added_count, was_merged, total_students)
    or (None, error_msg, False, 0)."""
    if not is_connected():
        return None, "MongoDB not connected", False, 0
    try:
        oid = ObjectId(batch_id)
        existing = _batches_coll().find_one({"_id": oid})
        if existing is None:
            return None, "Batch not found", False, 0

        existing_usns = set(
            s["usn"] for s in _students_coll().find({"batch_id": oid}, {"usn": 1})
        )
        new_docs = [d for d in student_docs if d["usn"] not in existing_usns]
        new_docs.sort(key=lambda d: d.get("usn", ""))
        for s in new_docs:
            s["batch_id"] = oid
        if new_docs:
            _students_coll().insert_many(new_docs)

        total = _students_coll().count_documents({"batch_id": oid})
        merged_subjects = sorted(
            set(existing.get("subjects") or []) | set(batch_doc.get("subjects") or [])
        )
        _batches_coll().update_one(
            {"_id": oid},
            {"$set": {
                "student_count": total,
                "subjects": merged_subjects,
                "saved_at": datetime.utcnow(),
            }},
        )
        return str(oid), len(new_docs), True, total
    except PyMongoError as e:
        return None, str(e), False, 0


def fetch_batches(limit=100):
    """Return saved batches, newest first."""
    if not is_connected():
        return []
    try:
        docs = list(_batches_coll().find().sort("saved_at", -1).limit(limit))
        return [_jsonable(d) for d in docs]
    except PyMongoError as e:
        print(f"[MongoDB] fetch_batches error: {e}")
        return []


def distinct_batch_values(field):
    """Return unique, non-empty values of a batch field (semester/scheme/year/...).
    Used to populate filter dropdowns directly from the database."""
    if not is_connected():
        return []
    try:
        values = _batches_coll().distinct(field)
        return [str(v) for v in values if v is not None and str(v).strip() != ""]
    except PyMongoError as e:
        print(f"[MongoDB] distinct_batch_values error: {e}")
        return []


def fetch_batch(batch_id):
    """Return one batch doc (JSON-safe) or None."""
    if not is_connected() or not ObjectId.is_valid(batch_id):
        return None
    try:
        doc = _batches_coll().find_one({"_id": ObjectId(batch_id)})
        return _jsonable(doc) if doc else None
    except PyMongoError as e:
        print(f"[MongoDB] fetch_batch error: {e}")
        return None


def fetch_students(batch_id):
    """Return student docs for one batch (JSON-safe) or []."""
    if not is_connected() or not ObjectId.is_valid(batch_id):
        return []
    try:
        docs = list(_students_coll().find({"batch_id": ObjectId(batch_id)}).sort("usn", 1))
        return [_jsonable(d) for d in docs]
    except PyMongoError as e:
        print(f"[MongoDB] fetch_students error: {e}")
        return []


def fetch_student_record(usn):
    """Fetch all semester results for a USN across all batches.

    Returns {usn, name, semesters: [{batch_id, semester, scheme, year, department,
    subjects, percentage, result_status, saved_at}]} sorted by semester number.
    """
    if not is_connected():
        return None
    try:
        usn = usn.strip().upper()
        students = list(_students_coll().find({"usn": usn}).sort("usn", 1))
        if not students:
            return None

        name = ""
        semesters = []
        seen_sem = set()
        for s in students:
            batch = _batches_coll().find_one({"_id": s["batch_id"]})
            if not batch:
                continue
            rtype = batch.get("result_type", "original")
            sem = batch.get("semester", "?")
            key = f"{sem}_{rtype}"
            if key in seen_sem:
                continue
            seen_sem.add(key)
            if not name:
                name = s.get("name", "")
            semesters.append({
                "batch_id": str(s["batch_id"]),
                "semester": sem,
                "scheme": batch.get("scheme", ""),
                "year": batch.get("year", ""),
                "department": batch.get("department", ""),
                "subjects": s.get("subjects", []),
                "percentage": s.get("percentage"),
                "result_status": s.get("result_status", ""),
                "saved_at": batch.get("saved_at", ""),
                "result_type": rtype,
            })

        def sem_sort_key(x):
            try:
                return int(x.get("semester", 99))
            except (ValueError, TypeError):
                return 99
        semesters.sort(key=sem_sort_key)

        return {"usn": usn, "name": name, "semesters": semesters}
    except PyMongoError as e:
        print(f"[MongoDB] fetch_student_record error: {e}")
        return None


def fetch_batch_with_students(batch_id):
    """Convenience: (batch_doc, student_docs) or (None, None) if not found."""
    batch = fetch_batch(batch_id)
    if batch is None:
        return None, None
    return batch, fetch_students(batch_id)


# -----------------------------------------
# REVALUATION SUPPORT
# -----------------------------------------

def save_revaluation(original_batch_id, batch_doc, student_docs):
    """Save revaluation results linked to an original batch.

    Creates a new batch with result_type='revaluation' and stores the
    original_batch_id reference. Comparison is computed on demand, not stored.
    Returns (reval_batch_id, added_count, error_msg).
    """
    if not is_connected():
        return None, 0, "MongoDB not connected"
    try:
        batch_doc["result_type"] = "revaluation"
        batch_doc["original_batch_id"] = original_batch_id

        reval_batch_id = _batches_coll().insert_one(batch_doc).inserted_id

        # Deduplicate USNs within this batch
        seen_usns = set()
        unique_docs = []
        for s in student_docs:
            u = s.get("usn", "")
            if u and u not in seen_usns:
                seen_usns.add(u)
                s["batch_id"] = reval_batch_id
                unique_docs.append(s)

        if unique_docs:
            _students_coll().insert_many(unique_docs)

        return str(reval_batch_id), len(unique_docs), None
    except PyMongoError as e:
        return None, 0, str(e)


def get_revaluation_comparison(reval_batch_id, original_batch_id=None):
    """Get revaluation comparison data for all students in a reval batch.

    If original_batch_id is provided, compares against that batch.
    Otherwise uses the linked original_batch_id from the reval batch doc.
    Returns list of {usn, name, comparison: [...], summary: {...}}.
    """
    if not is_connected():
        return []
    try:
        # Resolve original batch
        if not original_batch_id:
            reval_doc = _batches_coll().find_one({"_id": ObjectId(reval_batch_id)})
            if reval_doc and reval_doc.get("original_batch_id"):
                original_batch_id = str(reval_doc["original_batch_id"])

        orig_students = fetch_students(original_batch_id) if original_batch_id else []
        orig_map = {}
        for s in orig_students:
            orig_map[s["usn"]] = s

        reval_students = fetch_students(reval_batch_id)
        results = []
        for s in reval_students:
            usn = s.get("usn", "")
            orig = orig_map.get(usn)
            comp = []

            reval_subs = {sub["code"]: sub for sub in s.get("subjects", [])}
            orig_subs = {}
            if orig:
                orig_subs = {sub["code"]: sub for sub in orig.get("subjects", [])}

            all_codes = sorted(set(list(reval_subs.keys()) + list(orig_subs.keys())))

            for code in all_codes:
                reval_sub = reval_subs.get(code, {})
                orig_sub = orig_subs.get(code, {})

                orig_total = orig_sub.get("total")
                new_total = reval_sub.get("total")
                orig_internal = orig_sub.get("internal")
                new_internal = reval_sub.get("internal")
                orig_external = orig_sub.get("external")
                new_external = reval_sub.get("external")
                orig_result = orig_sub.get("result", "")
                new_result = reval_sub.get("result", "")

                change = 0
                status = "No Change"
                if orig_total is not None and new_total is not None:
                    change = (new_total or 0) - (orig_total or 0)
                    if change > 0:
                        status = "Improved"
                    elif change < 0:
                        status = "Decreased"
                    else:
                        status = "No Change"
                elif orig_total is None and new_total is not None:
                    status = "New"
                elif orig_total is not None and new_total is None:
                    status = "Removed"

                result_changed = ""
                if orig_result != new_result:
                    if orig_result == "F" and new_result != "F":
                        result_changed = "New Pass"
                    elif orig_result != "F" and new_result == "F":
                        result_changed = "New Fail"
                    else:
                        result_changed = "Grade Changed"

                comp.append({
                    "code": code,
                    "subject_name": reval_sub.get("subject_name", "") or orig_sub.get("subject_name", ""),
                    "orig_total": orig_total,
                    "new_total": new_total,
                    "orig_internal": orig_internal,
                    "new_internal": new_internal,
                    "orig_external": orig_external,
                    "new_external": new_external,
                    "orig_result": orig_result,
                    "new_result": new_result,
                    "change": change,
                    "status": status,
                    "result_changed": result_changed,
                })

            improved = sum(1 for c in comp if c["status"] == "Improved")
            decreased = sum(1 for c in comp if c["status"] == "Decreased")
            no_change = sum(1 for c in comp if c["status"] == "No Change")
            new_pass = sum(1 for c in comp if c["result_changed"] == "New Pass")
            orig_total_sum = sum(c.get("orig_total") or 0 for c in comp if c.get("orig_total") is not None)
            new_total_sum = sum(c.get("new_total") or 0 for c in comp if c.get("new_total") is not None)

            results.append({
                "usn": usn,
                "name": s.get("name", ""),
                "percentage": s.get("percentage"),
                "result_status": s.get("result_status", ""),
                "comparison": comp,
                "summary": {
                    "improved": improved,
                    "decreased": decreased,
                    "no_change": no_change,
                    "new_pass": new_pass,
                    "orig_total": orig_total_sum,
                    "new_total": new_total_sum,
                    "total_change": new_total_sum - orig_total_sum,
                },
            })
        return results
    except Exception as e:
        print(f"[MongoDB] get_revaluation_comparison error: {e}")
        return []


def find_original_batch(reval_batch_id):
    """Find the original batch linked to a revaluation batch."""
    if not is_connected():
        return None
    try:
        reval = _batches_coll().find_one({"_id": ObjectId(reval_batch_id)})
        if reval and reval.get("original_batch_id"):
            return fetch_batch(reval["original_batch_id"])
        return None
    except Exception:
        return None
