import sqlite3

SIM_DB = "db_files/dex_pipeline_local_sim_mod.db"
MAIN_DB = "db_files/dex_pipeline_local_mod.db"

def move_back():
    sim_conn = sqlite3.connect(SIM_DB)
    main_conn = sqlite3.connect(MAIN_DB)

    cur_main = main_conn.cursor()
    cur_main.execute("SELECT pair_id, time, open, high, low, close, volume FROM ohlc_data")
    rows = cur_main.fetchall()

    if not rows:
        print("⚠️ No rows to move back")
        return

    # Insert back into sim DB
    cur_sim = sim_conn.cursor()
    cur_sim.executemany("""
        INSERT OR REPLACE INTO ohlc_data (pair_id, time, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    sim_conn.commit()

    # Delete from main DB
    cur_main.execute("DELETE FROM ohlc_data")
    main_conn.commit()

    print(f"✅ Moved {len(rows)} rows back to sim DB")

    main_conn.close()
    sim_conn.close()

if __name__ == "__main__":
    move_back()
