from datetime import datetime, timezone
import time

from core.db_utils import get_db_connection
from trading.trade_executor import run_trades
from trading.trade_2 import build_trade_signals


def acquire_lock():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO module_control (module_name, status)
        VALUES ('trade_engine', 'OFF')
    """)
    cur.execute("""
        UPDATE module_control SET status='ON'
        WHERE module_name='trade_engine' AND status='OFF'
    """)
    acquired = cur.rowcount > 0
    conn.commit()
    conn.close()
    return acquired


def release_lock():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE module_control SET status='OFF'
        WHERE module_name='trade_engine' AND status='ON'
    """)
    conn.commit()
    conn.close()


def remove_pending(ids):
    if not ids:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.executemany("DELETE FROM pending_trades WHERE id=?", [(i,) for i in ids])
    conn.commit()
    conn.close()


def insert_live_trade(contract):
    """Insert a confirmed BUY into live_trades. Updates trade_risk_state with actual execution price."""
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)

    cur.execute("SELECT pair_id FROM supported_tokens WHERE contract=?", (contract,))
    row = cur.fetchone()
    pair_id = row[0] if row else contract

    cur.execute("SELECT close FROM ohlc_data WHERE pair_id=? ORDER BY time DESC LIMIT 1", (pair_id,))
    price_row = cur.fetchone()
    actual_price = float(price_row[0]) if price_row and price_row[0] else None

    cur.execute("SELECT hard_stop_pct FROM trade_risk_state WHERE pair_id=?", (pair_id,))
    rs = cur.fetchone()
    hard_stop_pct = rs[0] if rs and rs[0] else 0.10

    if actual_price:
        stop_price = actual_price * (1 - hard_stop_pct)
        cur.execute("""
            UPDATE trade_risk_state
            SET entry_price=?, current_price=?, peak_price=?, stop_price=?, last_updated=?
            WHERE pair_id=?
        """, (actual_price, actual_price, actual_price, stop_price, now, pair_id))
        entry_price = actual_price
    else:
        cur.execute("SELECT entry_price FROM trade_risk_state WHERE pair_id=?", (pair_id,))
        fb = cur.fetchone()
        entry_price = fb[0] if fb and fb[0] else 0.0

    cur.execute("""
        INSERT OR REPLACE INTO live_trades (
            pair_id, contract, entry_price, entry_time,
            status, decision, peak_price, trailing_active, last_update
        ) VALUES (?, ?, ?, ?, 'OPEN', 1, ?, 0, ?)
    """, (pair_id, contract, entry_price, now, entry_price, now))
    conn.commit()
    conn.close()


def remove_live_trade(contract):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM live_trades WHERE contract=?", (contract,))
    conn.commit()
    conn.close()


def run_trade_engine():
    if not acquire_lock():
        print("[Trade] Engine already running — skipping")
        return

    try:
        trade_signals, pending_map = build_trade_signals()
        if not trade_signals:
            print("[Trade] No trades to execute")
            return

        successful_signals: list = []
        failed_signals: list     = list(trade_signals)
        try:
            successful_signals, failed_signals = run_trades(trade_signals)
        except Exception as e:
            print(f"[Trade] Execution failed: {e}")
            # fall through — successful_signals is empty so no DB mutations happen

        ids_to_remove = [
            pending_map.get(s["token_mint"])
            for s in successful_signals
            if pending_map.get(s["token_mint"])
        ]
        remove_pending(ids_to_remove)

        for s in successful_signals:
            if s["type"] == "BUY":
                insert_live_trade(s["token_mint"])
                try:
                    from notify.reports import notify_trade_entry
                    conn2 = get_db_connection()
                    cur2  = conn2.cursor()
                    cur2.execute(
                        "SELECT entry_price FROM live_trades WHERE contract=?",
                        (s["token_mint"],)
                    )
                    ep_row = cur2.fetchone()
                    conn2.close()
                    notify_trade_entry(
                        s["token_mint"],
                        s.get("amount", 0.0),
                        float(ep_row[0]) if ep_row and ep_row[0] else 0.0,
                    )
                except Exception:
                    pass
            elif s["type"] == "SELL":
                remove_live_trade(s["token_mint"])

        print(f"[Trade] Complete — success: {len(successful_signals)}, failed: {len(failed_signals)}")

    finally:
        release_lock()


if __name__ == "__main__":
    run_trade_engine()
