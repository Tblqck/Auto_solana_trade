# ai_signal_updater.py
import pandas as pd
from datetime import datetime, timezone
from core.db_utils import get_db_connection

TABLE_NAME = "ai_thought"


def update_ai_signals(signals_df: pd.DataFrame):
    """
    Upsert AI signals into ai_thought table without dropping it.
    Existing rows are updated in place; rows no longer in signals are marked DECISION=0.
    """
    if signals_df.empty:
        print("[AI] No signals to update.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Migration: if table exists with old schema (no PRIMARY KEY on pair_id), recreate it
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (TABLE_NAME,))
    table_exists = cursor.fetchone() is not None

    if table_exists:
        cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
        cols = {row[1]: row[5] for row in cursor.fetchall()}  # col_name -> pk (1 if PK, 0 if not)
        pair_id_is_pk = cols.get("pair_id", 0) == 1
        if not pair_id_is_pk:
            print("[AI] Migrating ai_thought table to new schema (one-time)")
            cursor.execute(f"DROP TABLE {TABLE_NAME}")
            conn.commit()

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            pair_id TEXT PRIMARY KEY,
            decision INTEGER,
            time_queued TIMESTAMP,
            trade_stat INTEGER,
            last_price REAL,
            in_price REAL,
            last_price_older REAL,
            time_inprice TIMESTAMP,
            clf_prob REAL,
            reg_pred REAL
        )
    """)
    conn.commit()

    new_signals_map = {
        row["pair_id"]: row
        for _, row in signals_df.iterrows()
    }

    # Mark tokens no longer in BUY signals as DECISION=0
    cursor.execute(f"SELECT pair_id FROM {TABLE_NAME}")
    existing_ids = {row[0] for row in cursor.fetchall()}
    stale_ids = existing_ids - set(new_signals_map.keys())
    for pair_id in stale_ids:
        cursor.execute(
            f"UPDATE {TABLE_NAME} SET decision=0, time_queued=? WHERE pair_id=?",
            (now_iso, pair_id)
        )

    # Upsert new/updated signals
    for pair_id, row in new_signals_map.items():
        # Preserve last_price as last_price_older for existing rows
        cursor.execute(f"SELECT last_price FROM {TABLE_NAME} WHERE pair_id=?", (pair_id,))
        existing = cursor.fetchone()
        last_price_older = existing[0] if existing else None

        cursor.execute(f"""
            INSERT INTO {TABLE_NAME}
                (pair_id, decision, time_queued, trade_stat,
                 last_price, in_price, last_price_older, time_inprice,
                 clf_prob, reg_pred)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pair_id) DO UPDATE SET
                decision        = excluded.decision,
                time_queued     = excluded.time_queued,
                trade_stat      = excluded.trade_stat,
                last_price      = excluded.last_price,
                last_price_older= excluded.last_price_older,
                clf_prob        = excluded.clf_prob,
                reg_pred        = excluded.reg_pred
        """, (
            pair_id,
            int(row.get("DECISION", 0)),
            now_iso,
            int(row.get("TRADE_STAT", 0)),
            row.get("LAST_PRICE"),
            row.get("IN_PRICE"),
            last_price_older,
            row.get("TIME_INPRICE"),
            row.get("clf_prob"),
            row.get("reg_pred"),
        ))

    conn.commit()
    conn.close()
    print(f"[AI] ai_thought updated: {len(new_signals_map)} active, {len(stale_ids)} marked inactive")
