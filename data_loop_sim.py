# data_loop_sim.py
"""
Simulated Data Loop for OHLC Streaming
Copies data from sim DB -> main DB row by row
First run: 24h batch per token
Subsequent runs: single-row streaming
"""

import sqlite3
from datetime import datetime
from typing import List
from dateutil import parser  # safe timestamp parsing

SIM_DB = "db_files/dex_pipeline_local_sim_mod.db"
MAIN_DB = "db_files/dex_pipeline_local_mod.db"

# -----------------------------------
# DB Helpers
# -----------------------------------
def get_conn(db_path: str):
    """
    Return sqlite connection.
    Note: We disable automatic TIMESTAMP parsing to avoid Python 3.12+ issues.
    """
    return sqlite3.connect(
        db_path,
        detect_types=0,  # <-- disable automatic timestamp conversion
        check_same_thread=False
    )

# -----------------------------------
# Timestamp parser
# -----------------------------------
def parse_time(time_str: str) -> datetime:
    """Parse SQLite TIMESTAMP string robustly"""
    return parser.isoparse(time_str)

# -----------------------------------
# Fetch functions
# -----------------------------------
def fetch_tokens(sim_conn) -> List[str]:
    cur = sim_conn.cursor()
    cur.execute("SELECT DISTINCT pair_id FROM ohlc_data ORDER BY pair_id")
    return [row[0] for row in cur.fetchall()]

def fetch_first_24h(sim_conn, pair_id: str):
    cur = sim_conn.cursor()
    cur.execute("""
        SELECT pair_id, time, open, high, low, close, volume
        FROM ohlc_data
        WHERE pair_id = ?
        ORDER BY time ASC
        LIMIT 1440
    """, (pair_id,))
    rows = cur.fetchall()

    converted_rows = []
    for row in rows:
        pair, time_str, o, h, l, c, v = row
        time_dt = parse_time(time_str)
        converted_rows.append((pair, time_dt, o, h, l, c, v))
    return converted_rows

def fetch_next_row(sim_conn, pair_id: str):
    cur = sim_conn.cursor()
    cur.execute("""
        SELECT pair_id, time, open, high, low, close, volume
        FROM ohlc_data
        WHERE pair_id = ?
        ORDER BY time ASC
        LIMIT 1
    """, (pair_id,))
    row = cur.fetchone()
    if not row:
        return None
    pair, time_str, o, h, l, c, v = row
    time_dt = parse_time(time_str)
    return (pair, time_dt, o, h, l, c, v)

# -----------------------------------
# Insert & Delete
# -----------------------------------
def insert_rows(main_conn, rows):
    cur = main_conn.cursor()
    cur.executemany("""
        INSERT OR REPLACE INTO ohlc_data
        (pair_id, time, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    main_conn.commit()

def delete_rows(sim_conn, rows):
    cur = sim_conn.cursor()
    times = [(r[0], r[1].isoformat()) for r in rows]
    cur.executemany("""
        DELETE FROM ohlc_data WHERE pair_id = ? AND time = ?
    """, times)
    sim_conn.commit()

def delete_row(sim_conn, row):
    cur = sim_conn.cursor()
    pair_id, time_dt, *_ = row
    cur.execute("DELETE FROM ohlc_data WHERE pair_id = ? AND time = ?", (pair_id, time_dt.isoformat()))
    sim_conn.commit()

# -----------------------------------
# Main Loop
# -----------------------------------
def run_data_loop_sim(first_run=False):
    sim_conn = get_conn(SIM_DB)
    main_conn = get_conn(MAIN_DB)

    try:
        pair_ids = fetch_tokens(sim_conn)
        if not pair_ids:
            print("⚠️ No tokens with data in sim DB")
            return

        for pair_id in pair_ids:
            if first_run:
                # Copy first 24h in batch
                rows = fetch_first_24h(sim_conn, pair_id)
                if not rows:
                    continue
                insert_rows(main_conn, rows)
                delete_rows(sim_conn, rows)
                print(f"✅ {pair_id}: first 24h inserted ({len(rows)} rows)")
            else:
                # Stream one row at a time
                row = fetch_next_row(sim_conn, pair_id)
                if not row:
                    continue
                insert_rows(main_conn, [row])
                delete_row(sim_conn, row)
                print(f"⏩ {pair_id}: streamed row {row[1]}")

    finally:
        sim_conn.close()
        main_conn.close()

# -----------------------------------
# CLI
# -----------------------------------
if __name__ == "__main__":
    run_data_loop_sim(first_run=True)
