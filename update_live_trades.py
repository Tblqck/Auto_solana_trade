from datetime import datetime, timezone
from db_utils import get_db_connection2

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

    # ---------------- SAFE & SAFE_HOLD → create/update PENDING BUY ----------------
    for pair_list in [results.get("safe", []), results.get("safe_hold", [])]:
        for contract in pair_list:
            cur.execute("SELECT pairid FROM live_trades WHERE pairid=?", (contract,))
            row = cur.fetchone()
            if row is None:
                # Insert new PENDING buy
                cur.execute("""
                    INSERT INTO live_trades (pairid, contract, decision, status, entry_time, source, last_update)
                    VALUES (?, ?, 1, 'PENDING', ?, ?, ?)
                """, (contract, contract, now, source, now))
            else:
                # Update existing row if needed
                cur.execute("""
                    UPDATE live_trades
                    SET decision=1, status='PENDING', last_update=?
                    WHERE pairid=?
                """, (now, contract))

    # ---------------- BLOCKED & NO_DATA → mark for sell (PENDING_CLOSE) ----------------
    for pair_list in [results.get("blocked", []), results.get("no_data", [])]:
        for contract in pair_list:
            cur.execute("SELECT pairid, status FROM live_trades WHERE pairid=?", (contract,))
            row = cur.fetchone()
            if row:
                # Only update if trade is currently active or pending
                if row[1] in ("OPEN", "PENDING"):
                    cur.execute("""
                        UPDATE live_trades
                        SET decision=0, status='PENDING_CLOSE', last_update=?
                        WHERE pairid=?
                    """, (now, contract))
            else:
                # Optionally create a row if never existed
                cur.execute("""
                    INSERT INTO live_trades (pairid, contract, decision, status, entry_time, source, last_update)
                    VALUES (?, ?, 0, 'PENDING_CLOSE', ?, ?, ?)
                """, (contract, contract, now, source, now))

    conn.commit()
    conn.close()
