# watcher.py (DB version, fixed, continuous 30s)
import time
from db_utils import get_db_connection
from watcher_core import run_watcher_signal_based  # new signal-based watcher

WATCHER_NAME = "WATCHER"

# ---------------------------
# DB helpers
# ---------------------------
def is_module_on(module_name: str) -> bool:
    """Check if module is ON in module_control table"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM module_control WHERE module_name = ?",
        (module_name,),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0].upper() == "ON"


def set_module_status(module_name: str, status: str):
    """Set module status in module_control table"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO module_control (module_name, status)
        VALUES (?, ?)
        ON CONFLICT(module_name)
        DO UPDATE SET status = excluded.status
        """,
        (module_name, status),
    )
    conn.commit()
    conn.close()


# ---------------------------
# Main watcher loop
# ---------------------------
def watcher(interval=30):  # 30 seconds loop
    print("👀 Watcher (DB) started")

    # mark as ON
    set_module_status(WATCHER_NAME, "ON")

    try:
        while True:
            if not is_module_on(WATCHER_NAME):
                print("⏹️ Watcher disabled from DB")
                break

            # Run signal-based watcher
            run_watcher_signal_based()

            # wait before next iteration
            print(f"⏳ Sleeping {interval}s before next loop")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("🛑 Watcher interrupted by user")

    finally:
        set_module_status(WATCHER_NAME, "OFF")
        print("🛑 Watcher stopped safely")


# ---------------------------
# ENTRY
# ---------------------------
if __name__ == "__main__":
    watcher()