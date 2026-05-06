from datetime import datetime, timezone
import subprocess

from core.db_utils import get_db_connection2

get_db_connection = get_db_connection2
TRADE_ENGINE_MODULE = "trade_engine"


def get_contract_for_pair(pair_id: str) -> str | None:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT contract FROM supported_tokens WHERE pair_id=?", (pair_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def fetch_live_trades() -> set:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT contract FROM live_trades WHERE status IN ('OPEN', 'PENDING_CLOSE')")
    rows = cur.fetchall()
    conn.close()
    return {r[0] for r in rows if r[0]}


def fetch_pending_actions() -> set:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT contract, decision FROM pending_trades")
    rows = cur.fetchall()
    conn.close()
    return {(r[0], r[1]) for r in rows}


def queue_trade(contract: str, decision: int):
    """Insert into pending_trades only if no identical (contract, decision) row already exists.
    Check and insert in one connection to prevent duplicate queuing under concurrent cycles."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pending_trades WHERE contract=? AND decision=? LIMIT 1",
        (contract, decision),
    )
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO pending_trades (contract, decision, time_queued) VALUES (?, ?, ?)",
            (contract, decision, datetime.now(timezone.utc)),
        )
        conn.commit()
    conn.close()


def trade_engine_status() -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (TRADE_ENGINE_MODULE,))
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0] == "ON")


def start_trade_engine():
    subprocess.Popen(["python", "-m", "trading.trade"])
    print("[Watcher] Trade engine launched")


def run_watcher_signal_based():
    from signals.signal_pipeline import run_signal_pipeline

    print("[Watcher] Running signal cycle")

    signals = run_signal_pipeline()
    new_safe = signals.get("new_safe", [])
    sell = signals.get("sell", [])

    live_contracts = fetch_live_trades()
    pending_actions = fetch_pending_actions()

    for pair_id in new_safe:
        contract = get_contract_for_pair(pair_id)
        if not contract:
            print(f"[Watcher] No contract for pair {pair_id} — skipping BUY")
            continue
        if contract in live_contracts:
            continue
        if (contract, 1) in pending_actions:
            continue
        queue_trade(contract, 1)
        print(f"[Watcher] BUY queued: {contract} (pair: {pair_id})")

    for pair_id in sell:
        contract = get_contract_for_pair(pair_id)
        if not contract:
            print(f"[Watcher] No contract for pair {pair_id} — skipping SELL")
            continue
        if contract not in live_contracts:
            continue
        if (contract, 0) in pending_actions:
            continue
        queue_trade(contract, 0)
        print(f"[Watcher] SELL queued: {contract} (pair: {pair_id})")

    if not trade_engine_status():
        print("[Watcher] Trade engine not running — launching")
        start_trade_engine()
    else:
        print("[Watcher] Trade engine already running")

    print("[Watcher] Cycle complete")


if __name__ == "__main__":
    run_watcher_signal_based()
