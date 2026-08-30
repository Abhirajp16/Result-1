import time
from dotenv import load_dotenv
import os
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGODB_URI")
db_name = os.getenv("MONGODB_DB_NAME", "vtu_results")

print("Testing MongoDB connection in a loop...")
print("URI:", uri[:45] + "...")
print("DB:", db_name)
print()

attempt = 0
while True:
    attempt += 1
    print("--- Attempt %d ---" % attempt)
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        client.admin.command("ping")
        db = client[db_name]
        print("[OK] Connected to MongoDB:", db_name)

        # Write a test document
        test_doc = {
            "test": True,
            "attempt": attempt,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        result = db["connection_tests"].insert_one(test_doc)
        print("[OK] Wrote test doc _id:", result.inserted_id)

        # Count test docs
        count = db["connection_tests"].count_documents({})
        print("[OK] Total test docs:", count)

        # List collections
        cols = db.list_collection_names()
        print("[OK] Collections:", cols)

        # Check fetch_batches
        if "fetch_batches" in cols:
            batches = list(db["fetch_batches"].find().sort("saved_at", -1).limit(3))
            print("[OK] Recent batches:", len(batches))
        else:
            print("[OK] No fetch_batches yet (empty DB)")

        client.close()
        print("[OK] LOOP OK - retesting in 5s. Ctrl+C to stop.\n")
        time.sleep(5)

    except Exception as e:
        print("[FAIL]", type(e).__name__, str(e)[:200])
        print("Retrying in 5s...\n")
        time.sleep(5)
