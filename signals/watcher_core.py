from datetime import datetime, timezone
import subprocess

from core.db_utils import get_db_connection2
from risk.entry_spark import check_entry_spark

get_db_connection = get_db_connection2
TRADE_ENGINE_MODULE = "trade_engine"


def check_reg_pred_positive(pair_id: str, conn) -> bool:
    """Return False only when the regressor explicitly predicts price decline.
    Falls back to True when data is missing so we never block on stale/absent rows."""
    cur = conn.cursor()
    cur.execute(
        "SELECT reg_pred, LAST_PRICE FROM ai_thought WHERE pair_id = ? LIMIT 1",
        (pair_id,)
    )
    row = cur.fetchone()
    if not row or row[0] is None or row[1] is None or float(row[1]) <= 0:
        return True
    result = float(row[0]) > float(row[1])
    if not result:
        print(f"[Watcher] BUY held — reg_pred {float(row[0]):.6f} < price {float(row[1]):.6f}: {pair_id}")
    return result


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


def _ensure_reason_column():
    """Add reason column to pending_trades if it doesn't exist yet."""
    conn = get_db_connection()
    try:
        conn.execute("ALTER TABLE pending_trades ADD COLUMN reason TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass
    conn.close()

_ensure_reason_column()


def queue_trade(contract: str, decision: int, reason: str = None):
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
            "INSERT INTO pending_trades (contract, decision, time_queued, reason) VALUES (?, ?, ?, ?)",
            (contract, decision, datetime.now(timezone.utc), reason),
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
    sell_reasons = signals.get("sell_reasons", {})

    live_contracts = fetch_live_trades()
    pending_actions = fetch_pending_actions()

    spark_conn = get_db_connection()
    try:
        for pair_id in new_safe:
            contract = get_contract_for_pair(pair_id)
            if not contract:
                print(f"[Watcher] No contract for pair {pair_id} — skipping BUY")
                continue
            if contract in live_contracts:
                continue
            if (contract, 1) in pending_actions:
                continue
            if not check_entry_spark(pair_id, spark_conn):
                print(f"[Watcher] BUY held — no momentum spark: {pair_id}")
                continue
            if not check_reg_pred_positive(pair_id, spark_conn):
                continue
            queue_trade(contract, 1)
            print(f"[Watcher] BUY queued: {contract} (pair: {pair_id})")
    finally:
        spark_conn.close()

    for pair_id in sell:
        contract = get_contract_for_pair(pair_id)
        if not contract:
            print(f"[Watcher] No contract for pair {pair_id} — skipping SELL")
            continue
        if contract not in live_contracts:
            continue
        if (contract, 0) in pending_actions:
            continue
        reason = sell_reasons.get(pair_id, "SIGNAL")
        queue_trade(contract, 0, reason=reason)
        print(f"[Watcher] SELL queued [{reason}]: {contract} (pair: {pair_id})")

    if not trade_engine_status():
        print("[Watcher] Trade engine not running — launching")
        start_trade_engine()
    else:
        print("[Watcher] Trade engine already running")

    print("[Watcher] Cycle complete")


if __name__ == "__main__":
    run_watcher_signal_based()
