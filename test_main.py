# test_watcher.py
import time
import threading
from signals.watcher import watcher
from core.db_utils import get_db_connection


# -----------------------------
# DB check helpers
# -----------------------------
def get_module_status(name):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (name,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# -----------------------------
# Run watcher in background
# -----------------------------
def run_watcher_test():
    print("🚀 Starting watcher test...")

    t = threading.Thread(target=watcher, kwargs={"interval": 5}, daemon=True)
    t.start()

    # let system warm up
    time.sleep(8)

    # -----------------------------
    # Check 1: watcher ON?
    # -----------------------------
    status = get_module_status("WATCHER")
    print(f"📌 WATCHER status: {status}")

    # -----------------------------
    # Check 2: let DataLoop run a bit
    # -----------------------------
    print("⏳ Letting DataLoop + signals run...")
    time.sleep(15)

    # -----------------------------
    # Final status check
    # -----------------------------
    status = get_module_status("WATCHER")
    print(f"📌 Final WATCHER status: {status}")

    print("🧪 Test completed (watcher still running in background daemon thread)")


# -----------------------------
# ENTRY
# -----------------------------
if __name__ == "__main__":
    run_watcher_test()