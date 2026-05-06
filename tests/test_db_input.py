from datetime import datetime, timezone
from core.db_utils import get_db_connection


def insert_test_pending():

    signals = [
        {"type": "BUY",  "token_mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"},
        #{"type": "BUY",  "token_mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"},
        #{"type": "SELL", "token_mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"},
    ]

    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now(timezone.utc)

    rows = []

    for s in signals:
        decision = 1 if s["type"] == "BUY" else -1
        rows.append((
            s["token_mint"],
            decision,
            now
        ))

    cur.executemany("""
        INSERT INTO pending_trades (contract, decision, time_queued)
        VALUES (?, ?, ?)
    """, rows)

    conn.commit()
    conn.close()

    print("✅ Test pending trades inserted.")


if __name__ == "__main__":
    insert_test_pending()
