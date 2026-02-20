# db_creator_fixed.py
import sqlite3
import os

DB_PATH = "db_files/dex_pipeline_local_mod.db"

def get_db_connection():
    conn = sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )
    return conn

def drop_table(cursor, table_name):
    cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
    print(f"🗑 Dropped table (if existed): {table_name}")

def init_db():
    # Ensure folder exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = get_db_connection()
    cur = conn.cursor()

    # -------------------------
    # Drop old trade_risk_state table
    # -------------------------
    drop_table(cur, "trade_risk_state")

    # -------------------------
    # Create fresh trade_risk_state table
    # -------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trade_risk_state (
            pair_id TEXT PRIMARY KEY,
            
            entry_price REAL NOT NULL,
            current_price REAL NOT NULL,
            peak_price REAL NOT NULL,
            
            base_hard_stop_pct REAL NOT NULL,
            base_trail_start_pct REAL NOT NULL,
            base_trail_distance_pct REAL NOT NULL,
            
            hard_stop_pct REAL NOT NULL,
            trail_start_pct REAL NOT NULL,
            trail_distance_pct REAL NOT NULL,
            
            stop_price REAL NOT NULL,
            
            last_decision TEXT,        -- HOLD | EXIT
            trigger_type TEXT,
            last_updated TIMESTAMP NOT NULL
        )
    """)
    print("✅ Created fresh table: trade_risk_state")

    conn.commit()
    conn.close()
    print(f"✅ Database initialized successfully at {DB_PATH}")


if __name__ == "__main__":
    init_db()
