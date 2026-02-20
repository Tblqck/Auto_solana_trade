# watcher_core_v3.py
# --------------------------------------------------
# Watcher calls signal.py, updates pending_trades, and triggers trade.py
# --------------------------------------------------

from datetime import datetime, timezone
import subprocess

from db_utils import get_db_connection2
from signal_pipeline import run_signal_pipeline

get_db_connection = get_db_connection2
TRADE_ENGINE_MODULE = "trade_engine"


# ---------------------------
# DB helpers
# ---------------------------

def fetch_live_trades():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT pair_id FROM live_trades")
    rows = cur.fetchall()
    conn.close()
    return {r[0] for r in rows}


def fetch_pending_actions():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT contract, decision FROM pending_trades")
    rows = cur.fetchall()
    conn.close()
    return {(r[0], r[1]) for r in rows}


def queue_trade(contract, decision):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pending_trades (contract, decision, time_queued) VALUES (?, ?, ?)",
        (contract, decision, datetime.now(timezone.utc))
    )
    conn.commit()
    conn.close()


def trade_engine_status():
    """Returns True if trade_engine is ON"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (TRADE_ENGINE_MODULE,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == "ON")


def start_trade_engine():
    """Launch trade.py subprocess safely"""
    subprocess.Popen(["python", "trade.py"])
    print("🚀 Trade engine launched!")


# ---------------------------
# Watcher core
# ---------------------------

def run_watcher_signal_based():
    print("⏱️ Running watcher (signal-driven)")

    # 1 Get signals
    signals = run_signal_pipeline()
    new_safe = signals.get("new_safe", [])
    sell = signals.get("sell", [])

    # 2 Load current state
    live_pairs = fetch_live_trades()
    pending_actions = fetch_pending_actions()

    # --------------------------
    # Queue BUYs from new_safe
    # --------------------------
    for pair_id in new_safe:
        if pair_id in live_pairs:
            continue
        if (pair_id, 1) in pending_actions:
            continue
        queue_trade(pair_id, 1)
        print(f"BUY queued: {pair_id}")

    # --------------------------
    # Queue SELLs
    # --------------------------
    for pair_id in sell:
        if pair_id not in live_pairs:
            continue
        if (pair_id, 0) in pending_actions:
            continue
        queue_trade(pair_id, 0)
        print(f"SELL queued: {pair_id}")

    # --------------------------
    # Ensure trade.py is running
    # --------------------------
    if not trade_engine_status():
        print("Trade engine not running — launching...")
        start_trade_engine()
    else:
        print(" Trade engine already running. No action taken.")

    print("✅ Watcher cycle complete")


# ---------------------------
# ENTRY
# ---------------------------
if __name__ == "__main__":
    run_watcher_signal_based()