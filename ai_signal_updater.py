# ai_signal_updater.py
import pandas as pd
from datetime import datetime, timezone
from db_utils import get_db_connection

TABLE_NAME = "ai_thought"

def update_ai_signals(signals_df: pd.DataFrame):
    """
    Update the AI signals table in DB.

    Args:
        signals_df: DataFrame from trade_enricher with columns:
            ['ID', 'pair_id', 'DECISION', 'TIME_QUEUED', 'TRADE_STAT',
             'LAST_PRICE', 'IN_PRICE', 'LAST_PRICE_OLDER', 'TIME_INPRICE',
             'clf_prob', 'reg_pred']
    """
    if signals_df.empty:
        print("⚠️ No signals to update.")
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create table if it doesn't exist
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        id INTEGER PRIMARY KEY,
        pair_id TEXT,
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

    # Read existing table
    try:
        existing_df = pd.read_sql(f"SELECT * FROM {TABLE_NAME}", conn)
    except Exception:
        existing_df = pd.DataFrame()

    updated_rows = []

    # Map new signals by pair_id
    new_signals_map = {row["pair_id"]: row for _, row in signals_df.iterrows()}

    # Update existing rows
    for _, old_row in existing_df.iterrows():
        pair_id = old_row.get("pair_id")
        if pair_id in new_signals_map:
            new_row = new_signals_map[pair_id]
            row_dict = new_row.to_dict()
            row_dict["TIME_QUEUED"] = now_iso
            row_dict["LAST_PRICE_OLDER"] = old_row.get("last_price", None)
            updated_rows.append(row_dict)
            del new_signals_map[pair_id]
        else:
            row_dict = old_row.to_dict()
            row_dict["DECISION"] = 0
            row_dict["TIME_QUEUED"] = now_iso
            updated_rows.append(row_dict)

    # Add remaining new signals
    for new_row in new_signals_map.values():
        row_dict = new_row.to_dict()
        row_dict["TIME_QUEUED"] = now_iso
        row_dict["LAST_PRICE_OLDER"] = None
        updated_rows.append(row_dict)

    final_df = pd.DataFrame(updated_rows)

    # Overwrite table
    final_df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    print(f"✅ AI signals DB updated successfully. Total rows: {len(final_df)}.")
