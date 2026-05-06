# data_loop_stream.py
"""
Simulated Data Stream for OHLC
Copies one row at a time from sim DB -> main DB
Always picks the next row after the last inserted in main DB
"""

import sqlite3
from datetime import datetime
from typing import List, Optional

SIM_DB = "db_files/dex_pipeline_local_sim_mod.db"
MAIN_DB = "db_files/dex_pipeline_local_mod.db"

# -----------------------------------
# DB Helpers
# -----------------------------------
def get_conn(db_path: str):
    """Return sqlite connection WITHOUT automatic timestamp conversion"""
    return sqlite3.connect(
        db_path,
        detect_types=0,  # disable sqlite automatic timestamp parsing
        check_same_thread=False
    )

# -----------------------------------
# Fetch functions
# -----------------------------------
def fetch_tokens(sim_conn) -> List[str]:
    """Return all pair_ids in sim DB with remaining data"""
    cur = sim_conn.cursor()
    cur.execute("SELECT DISTINCT pair_id FROM ohlc_data ORDER BY pair_id")
    return [row[0] for row in cur.fetchall()]

def fetch_next_after_last(mod_conn, sim_conn, pair_id: str) -> Optional[tuple]:
    """
    Fetch the next row after the last row in mod DB.
    If no row exists in mod DB, pick the earliest from sim DB.
    """
    cur_mod = mod_conn.cursor()
    cur_mod.execute("SELECT MAX(time) FROM ohlc_data WHERE pair_id = ?", (pair_id,))
    last_time_row = cur_mod.fetchone()
    last_time = last_time_row[0] if last_time_row and last_time_row[0] else None

    cur_sim = sim_conn.cursor()
    if last_time:
        cur_sim.execute("""
            SELECT pair_id, time, open, high, low, close, volume
            FROM ohlc_data
            WHERE pair_id = ? AND time > ?
            ORDER BY time ASC
            LIMIT 1
        """, (pair_id, last_time))
    else:
        cur_sim.execute("""
            SELECT pair_id, time, open, high, low, close, volume
            FROM ohlc_data
            WHERE pair_id = ?
            ORDER BY time ASC
            LIMIT 1
        """, (pair_id,))

    row = cur_sim.fetchone()
    if not row:
        return None

    pair, time_str, o, h, l, c, v = row
    # Safe timestamp conversion
    try:
        time_dt = datetime.fromisoformat(str(time_str))
    except Exception:
        time_dt = datetime.strptime(str(time_str).split("+")[0], "%Y-%m-%d %H:%M:%S")

    return (pair, time_dt, o, h, l, c, v)

# -----------------------------------
# Insert & Delete
# -----------------------------------
def insert_row(main_conn, row):
    cur = main_conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO ohlc_data
        (pair_id, time, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, row)
    main_conn.commit()

def delete_row(sim_conn, row):
    cur = sim_conn.cursor()
    pair_id, time_dt, *_ = row
    cur.execute("DELETE FROM ohlc_data WHERE pair_id = ? AND time = ?", (pair_id, time_dt.isoformat()))
    sim_conn.commit()

# -----------------------------------
# Main Streaming Loop
# -----------------------------------
def run_data_stream():
    sim_conn = get_conn(SIM_DB)
    main_conn = get_conn(MAIN_DB)

    try:
        pair_ids = fetch_tokens(sim_conn)
        if not pair_ids:
            print("⚠️ No tokens with data in sim DB")
            return

        for pair_id in pair_ids:
            next_row = fetch_next_after_last(main_conn, sim_conn, pair_id)
            if not next_row:
                continue

            insert_row(main_conn, next_row)
            delete_row(sim_conn, next_row)
            print(f"⏩ {pair_id}: streamed row {next_row[1]}")

    finally:
        sim_conn.close()
        main_conn.close()

# -----------------------------------
# CLI
# -----------------------------------
if __name__ == "__main__":
    run_data_stream()
