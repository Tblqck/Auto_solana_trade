from datetime import datetime, timezone
from core.db_utils import get_db_connection2

def update_live_trades(results, source="AI"):
    """
    results: dict of sets
        results = {
            "safe": [...],
            "safe_hold": [...],
            "blocked": [...],
            "no_data": [...]
        }
    """
    conn = get_db_connection2()
    cur = conn.cursor()

    now = datetime.now(timezone.utc)

    # ---------------- SAFE & SAFE_HOLD → mark existing position as OPEN ----------------
    for pair_list in [results.get("safe", []), results.get("safe_hold", [])]:
        for contract in pair_list:
            cur.execute("SELECT pairid FROM live_trades WHERE pairid=?", (contract,))
            row = cur.fetchone()
            if row is not None:
                cur.execute("""
                    UPDATE live_trades
                    SET decision=1, status='OPEN', last_update=?
                    WHERE pairid=?
                """, (now, contract))
            # No INSERT here — live_trades rows are only created by trade.py after
            # a confirmed on-chain BUY, not by risk assessment.

    # ---------------- BLOCKED & NO_DATA → flag open positions for close ----------------
    for pair_list in [results.get("blocked", []), results.get("no_data", [])]:
        for contract in pair_list:
            cur.execute("SELECT pairid, status FROM live_trades WHERE pairid=?", (contract,))
            row = cur.fetchone()
            if row and row[1] == "OPEN":
                cur.execute("""
                    UPDATE live_trades
                    SET decision=0, status='PENDING_CLOSE', last_update=?
                    WHERE pairid=?
                """, (now, contract))
            # Never insert phantom rows for positions that don't exist in live_trades.

    conn.commit()
    conn.close()
