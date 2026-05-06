import time
from datetime import datetime, timezone

from ai.ai_orch import run_ai_cycle
from core.db_utils import get_db_connection


# ==========================================================
# DB helpers
# ==========================================================
def get_module_status(module: str) -> str:
    """Return the ON/OFF status of a module."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (module,))
    row = cur.fetchone()
    conn.close()
    return row[0].upper() if row and row[0] else "OFF"


def get_last_run(module: str):
    """Return last run datetime of a module, or None."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT last_run FROM module_status WHERE module_name=?", (module,))
    row = cur.fetchone()
    conn.close()

    if row and row[0]:
        dt = row[0] if not isinstance(row[0], str) else datetime.fromisoformat(row[0])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def set_module_status(module: str, status: str):
    """Set module ON/OFF in module_control table."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control(module_name, status)
        VALUES (?, ?)
        ON CONFLICT(module_name)
        DO UPDATE SET status=excluded.status
    """, (module, status))
    conn.commit()
    conn.close()


# ==========================================================
# AI cycle wrapper (single-shot, no DataLoop call)
# ==========================================================
def run_ai_bot_cycle():
    """Run a single AI bot cycle independently."""
    set_module_status("AI_BOT", "ON")
    print(f"[AI] Cycle started at {datetime.now(timezone.utc).isoformat()}")
    run_ai_cycle()
    set_module_status("AI_BOT", "OFF")
    print(f"[AI] Cycle complete")


# ==========================================================
# Looping function (optional service mode)
# ==========================================================
def start_ai_bot_loop(interval_seconds: int = 120):
    print(f"[AI] Starting loop (every {interval_seconds}s)")
    try:
        while True:
            run_ai_bot_cycle()
            print(f"[AI] Sleeping {interval_seconds}s before next cycle")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("[AI] Loop stopped manually")


# ==========================================================
# Standalone run (RUN ONCE)
# ==========================================================
if __name__ == "__main__":
    run_ai_bot_cycle()