# aibot.py
import time
from datetime import datetime, timezone

from ai_orch import run_ai_cycle
from Data_Loop import start_dataloop_agent
from db_utils import get_db_connection

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
# DataLoop guard
# ==========================================================
def should_start_dataloop(min_idle_seconds: int = 90) -> bool:
    """
    Check if DataLoop can start safely.
    """
    status = get_module_status("DataLoop")
    last_run = get_last_run("DataLoop")
    now = datetime.now(timezone.utc)

    if status == "ON":
        return False
    if last_run is None:
        return True

    idle = (now - last_run).total_seconds()
    return idle > min_idle_seconds


# ==========================================================
# AI cycle wrapper
# ==========================================================
def run_ai_bot_cycle():
    """Run a single safe AI bot cycle with DataLoop check."""
    set_module_status("AI_BOT", "ON")
    print(f"[{datetime.now(timezone.utc).isoformat()}] AI_BOT ON")

    # Start DataLoop safely
    if should_start_dataloop():
        print("🔄 Starting DataLoop agent")
        start_dataloop_agent()
    else:
        print("⏳ DataLoop recently active — not starting")

    # Wait until DataLoop updates last_run at least once
    while get_last_run("DataLoop") is None:
        print("⏳ Waiting for DataLoop to run...")
        time.sleep(2)

    # Run the AI prediction / enrichment / DB update cycle
    print("🤖 Running AI cycle")
    run_ai_cycle()

    set_module_status("AI_BOT", "OFF")
    print(f"[{datetime.now(timezone.utc).isoformat()}] AI_BOT OFF")


# ==========================================================
# Looping function for repeated execution
# ==========================================================
def start_ai_bot_loop(interval_seconds: int = 120):
    """
    Continuously run AI bot every `interval_seconds`.
    Can be imported and called from main.py
    """
    print(f"🚀 Starting AI bot loop (every {interval_seconds} seconds)...")
    try:
        while True:
            run_ai_bot_cycle()
            print(f"⏳ Waiting {interval_seconds} seconds before next cycle...\n")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("🛑 AI bot loop stopped manually.")


# ==========================================================
# Standalone run
# ==========================================================
if __name__ == "__main__":
    start_ai_bot_loop()
#from aibot import start_ai_bot_loop
#start_ai_bot_loop(interval_seconds=120)
