import time
import threading
import contextlib
import io

from core.db_utils import get_db_connection
from signals.watcher_core import run_watcher_signal_based
from data.Data_Loop_core import run_data_loop

WATCHER_NAME = "WATCHER"


def is_module_on(module_name: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name = ?", (module_name,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0].upper() == "ON"


def set_module_status(module_name: str, status: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control (module_name, status)
        VALUES (?, ?)
        ON CONFLICT(module_name) DO UPDATE SET status = excluded.status
    """, (module_name, status))
    conn.commit()
    conn.close()


def start_dataloop_background(interval_seconds=60, quiet=True):
    """Run DataLoop continuously in a background daemon thread."""
    def _loop():
        while True:
            try:
                if quiet:
                    with contextlib.redirect_stdout(io.StringIO()):
                        stats = run_data_loop()
                else:
                    print("[DataLoop] Background run triggered")
                    stats = run_data_loop()
                if stats:
                    try:
                        from notify.reports import accumulate_dataloop_stats
                        accumulate_dataloop_stats(
                            stats.get("pairs_checked", 0),
                            stats.get("rows_inserted", 0),
                        )
                    except Exception:
                        pass
            except Exception as e:
                print(f"[DataLoop] Background error: {e}")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    print(f"[Watcher] DataLoop background thread started (every {interval_seconds}s, quiet={quiet})")


def watcher(interval=30):
    print("[Watcher] Started")
    set_module_status(WATCHER_NAME, "ON")
    start_dataloop_background(interval_seconds=60, quiet=True)

    _REPORT_INTERVAL = 3600  # 1 hour
    last_report_ts   = time.time()

    try:
        while True:
            if not is_module_on(WATCHER_NAME):
                print("[Watcher] Disabled from DB — stopping")
                break

            run_watcher_signal_based()

            # Fire hourly reports
            if time.time() - last_report_ts >= _REPORT_INTERVAL:
                try:
                    from notify.reports import (
                        send_hourly_wallet_report,
                        send_hourly_dataloop_report,
                    )
                    send_hourly_wallet_report()
                    send_hourly_dataloop_report()
                except Exception as e:
                    print(f"[Watcher] Hourly report error: {e}")
                last_report_ts = time.time()

            print(f"[Watcher] Sleeping {interval}s before next cycle")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("[Watcher] Interrupted by user")

    finally:
        set_module_status(WATCHER_NAME, "OFF")
        print("[Watcher] Stopped safely")


if __name__ == "__main__":
    watcher(interval=10)
