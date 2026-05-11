# trade_signal_builder.py
from datetime import datetime, timezone, timedelta

from core.db_utils import get_db_connection
from wallet.allocation_manager import get_dynamic_allocation, claim_recycled_slot

MAX_SIGNAL_AGE_SECONDS = 60
MIN_TRADE_USDC         = 1.0


def fetch_pending_trades():
    conn = get_db_connection()
    cur  = conn.cursor()
    # reason column added at runtime — fall back gracefully if missing
    try:
        cur.execute("""
            SELECT id, contract, decision, time_queued, reason
            FROM pending_trades
            ORDER BY id ASC
            LIMIT 100
        """)
    except Exception:
        cur.execute("""
            SELECT id, contract, decision, time_queued, NULL
            FROM pending_trades
            ORDER BY id ASC
            LIMIT 100
        """)
    rows = cur.fetchall()
    conn.close()
    return rows


def purge_stale_pending():
    conn = get_db_connection()
    cur  = conn.cursor()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS)
    cur.execute("DELETE FROM pending_trades WHERE time_queued < ?", (cutoff,))
    purged = cur.rowcount
    conn.commit()
    conn.close()
    if purged:
        print(f"[Trade] Purged {purged} stale pending trade(s) (>{MAX_SIGNAL_AGE_SECONDS}s old)")


def contract_in_live_trade(contract: str) -> bool:
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT 1 FROM live_trades WHERE contract=? LIMIT 1", (contract,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def build_trade_signals() -> tuple[list, dict]:
    """Return (signals, pending_map) where pending_map is {contract: pending_id}.
    Both are built from the same DB fetch to avoid a double-query race window."""
    purge_stale_pending()

    pending      = fetch_pending_trades()
    # Build the map here so trade.py doesn't need a second fetch
    pending_map  = {contract: trade_id for trade_id, contract, _, _, _ in pending}

    sell_signals = []
    buy_signals  = []

    for _trade_id, contract, decision, _, reason in pending:
        decision = int(decision)

        if decision == 0:  # SELL
            sell_signals.append({"type": "SELL", "token_mint": contract, "_reason": reason or "SIGNAL"})
            continue

        if decision == 1:  # BUY
            if contract_in_live_trade(contract):
                print(f"[Trade] Skip BUY {contract[:8]}... already in live_trades")
                continue

            amount = claim_recycled_slot()
            source = "recycled"

            if amount < MIN_TRADE_USDC:
                amount = get_dynamic_allocation(hours=12)
                source = "planned"

            if amount < MIN_TRADE_USDC:
                print(f"[Trade] Skip BUY {contract[:8]}... allocation ${amount:.4f} < min")
                continue

            print(f"[Trade] BUY {contract[:8]}... via {source} slot -> ${amount:.4f}")
            buy_signals.append({
                "type":            "BUY",
                "token_mint":      contract,
                "amount":          float(amount),
                "_recycled_amount": float(amount) if source == "recycled" else 0.0,
            })

    # SELLs first (free capital), then BUYs
    signals = sell_signals + buy_signals
    return signals, pending_map


if __name__ == "__main__":
    signals = build_trade_signals()
    print("Trade signals ready:")
    print(signals)
