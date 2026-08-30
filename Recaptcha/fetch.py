import os
import sys
import subprocess
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(BASE_DIR, "bulk_fetcher_6.py")
CSV = os.path.join(BASE_DIR, "students.csv")

def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch.py <vtu_url> [usn1 usn2 ...]")
        print("   Or: python fetch.py <vtu_url>  (reads from students.csv)")
        sys.exit(1)

    vtu_url = sys.argv[1]
    usns = sys.argv[2:]

    if usns:
        with open(CSV, "w") as f:
            f.write("USN\n")
            for u in usns:
                f.write(u.strip().upper() + "\n")
        print(f"Written {len(usns)} USNs to students.csv")
    else:
        if not os.path.exists(CSV):
            print("Error: students.csv not found. Pass USNs as arguments.")
            sys.exit(1)
        with open(CSV) as f:
            count = len([l for l in f.readlines()[1:] if l.strip()])
        print(f"Reading {count} USNs from students.csv")

    print(f"Fetching results from: {vtu_url}")
    print("Starting...\n")

    result = subprocess.run(
        [sys.executable, BACKEND, vtu_url],
        cwd=BASE_DIR,
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    excel = os.path.join(BASE_DIR, "vtu_results.xlsx")
    if os.path.exists(excel):
        print(f"\nDone! Results saved to: {excel}")
    else:
        print("\nFailed to generate results.")

if __name__ == "__main__":
    main()
