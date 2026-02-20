# this is an agent for the data loop core 
import datetime
import threading
import time

from Data_Loop_core import run_data_loop, is_module_on
from db_utils import get_db_connection  # your DB helper


def get_last_run(module_name="DataLoop"):
    """Return the last_run datetime from module_status table as UTC-aware datetime."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT last_run FROM module_status WHERE module_name=?", (module_name,))
    row = cur.fetchone()
    conn.close()

    if row and row[0]:
        val = row[0]

        # If already datetime
        if isinstance(val, datetime.datetime):
            dt = val
        else:
            try:
                dt = datetime.datetime.fromisoformat(str(val))
            except Exception:
                return None

        # Convert naive datetimes to UTC-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt

    return None


def _agent_loop(min_interval_seconds=60, check_interval_seconds=10):
    """
    Internal loop that runs in a background thread.
    Checks if DataLoop needs to run and triggers it.
    """
    while True:
        try:
            # Skip if DataLoop is already running
            if is_module_on("DataLoop"):
                pass  # Already running
            else:
                last_run = get_last_run("DataLoop")
                now = datetime.datetime.now(datetime.timezone.utc)

                # Trigger DataLoop if never run or last run older than min_interval_seconds
                if last_run is None or (now - last_run).total_seconds() >= min_interval_seconds:
                    print(f"🔄 DataLoop Agent triggered at {now.isoformat()}")
                    run_data_loop()
        except Exception as e:
            print(f"❌ DataLoop Agent exception: {e}")

        time.sleep(check_interval_seconds)  # Non-blocking wait


def start_dataloop_agent(min_interval_seconds=60, check_interval_seconds=10):
    """
    Starts the DataLoop agent in a **background thread**.
    Returns immediately; the agent runs in the background.
    """
    thread = threading.Thread(
        target=_agent_loop,
        kwargs={
            "min_interval_seconds": min_interval_seconds,
            "check_interval_seconds": check_interval_seconds
        },
        daemon=True  # Daemon thread won't block program exit
    )
    thread.start()
    print("✅ DataLoop Agent started in background.")


# ----------------------------
# Standalone testing
# ----------------------------
if __name__ == "__main__":
    start_dataloop_agent(min_interval_seconds=60)
    print("DataLoop Agent is running in the background. Press Ctrl+C to stop.")
    while True:
        time.sleep(10)  # Keep main thread alive for testing
