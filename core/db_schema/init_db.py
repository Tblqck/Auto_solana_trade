# init_db.py
import sqlite3
import os

DB_PATH = "db_files/dex_pipeline_archive.db"  # default DB path

def get_db_connection():
    """Return a connection to the SQLite database."""
    return sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )

def init_db():
    """Initialize the database with all required tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db_connection()
    cur = conn.cursor()

    # tokens table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            Token TEXT,
            Symbol TEXT,
            Contract TEXT PRIMARY KEY,
            PairId TEXT,
            Price TEXT,
            MarketCap_raw REAL,
            Liquidity_raw REAL,
            FDV_raw REAL,
            MarketCap TEXT,
            Liquidity TEXT,
            FDV TEXT
        )
    """)

    # supported_tokens table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supported_tokens (
            Contract TEXT PRIMARY KEY,
            Token TEXT,
            Symbol TEXT,
            PairId TEXT,
            Price TEXT,
            MarketCap TEXT,
            Liquidity TEXT,
            FDV TEXT
        )
    """)

    # ohlc_data table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ohlc_data (
            pair_id TEXT,
            time TIMESTAMP,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY(pair_id, time)
        )
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {DB_PATH}")
