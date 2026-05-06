# db_table_stats.py
"""
View table statistics for both Main DB and Sim DB
Shows row counts and first/last timestamp if applicable
"""

import sqlite3

MAIN_DB = "db_files/dex_pipeline_local_mod.db"
SIM_DB = "db_files/dex_pipeline_local_sim_mod.db"

TABLES_TO_CHECK = ["tokens", "supported_tokens", "fetched_pairs", "ohlc_data"]

def get_conn(db_path):
    return sqlite3.connect(db_path, detect_types=0, check_same_thread=False)

def table_stats(conn, table_name):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = cur.fetchone()[0]

    # Check if table has a 'time' column
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = [c[1] for c in cur.fetchall()]
    time_info = ""
    if "time" in columns:
        cur.execute(f"SELECT MIN(time), MAX(time) FROM {table_name}")
        min_time, max_time = cur.fetchone()
        time_info = f" | min_time: {min_time} | max_time: {max_time}"

    return f"{table_name}: {count} rows{time_info}"

def print_db_stats(db_path):
    print(f"\n📊 Stats for DB: {db_path}")
    conn = get_conn(db_path)
    try:
        for table in TABLES_TO_CHECK:
            try:
                print("  " + table_stats(conn, table))
            except sqlite3.OperationalError:
                print(f"  {table}: ❌ does not exist in this DB")
    finally:
        conn.close()

if __name__ == "__main__":
    print_db_stats(MAIN_DB)
    print_db_stats(SIM_DB)
