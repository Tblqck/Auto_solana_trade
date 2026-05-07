# init_db.py
import sqlite3
import os

DB_PATH = os.path.join("db_files", "dex_pipeline.db")


def get_db_connection():
    return sqlite3.connect(
        DB_PATH,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
    )


def init_db():
    """Initialize the database with all required tables."""

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = get_db_connection()
    cur = conn.cursor()

    # -----------------------
    # Tokens scraped from Dexscreener
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT,
            symbol TEXT,
            contract TEXT PRIMARY KEY,
            pair_id TEXT,
            price TEXT,
            marketcap_raw REAL,
            liquidity_raw REAL,
            fdv_raw REAL,
            marketcap TEXT,
            liquidity TEXT,
            fdv TEXT
        )
    """)

    # -----------------------
    # Tokens supported by Jupiter
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS supported_tokens (
            contract TEXT PRIMARY KEY,
            token TEXT,
            symbol TEXT,
            pair_id TEXT,
            price TEXT,
            marketcap TEXT,
            liquidity TEXT,
            fdv TEXT
        )
    """)

    # -----------------------
    # Already fetched pairs
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fetched_pairs (
            pair_id TEXT PRIMARY KEY
        )
    """)

    # -----------------------
    # OHLC data
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ohlc_data (
            pair_id TEXT NOT NULL,
            time TIMESTAMP NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (pair_id, time)
        )
    """)

    # -----------------------
    # Trade risk state (LOSS GUARD CORE)
    # -----------------------
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

            last_decision TEXT,
            trigger_type TEXT,

            last_updated TIMESTAMP NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS loss_guard_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id TEXT NOT NULL,
            time_scanned TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            reason TEXT
        )
    """)

    # -----------------------
    # Module control
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS module_control (
            module_name TEXT PRIMARY KEY,
            status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS module_status (
            module_name TEXT PRIMARY KEY,
            last_run TIMESTAMP
        )
    """)

    # -----------------------
    # Live trades
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS live_trades (
            pair_id TEXT PRIMARY KEY,
            contract TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_time TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            decision INTEGER NOT NULL,
            stoploss REAL,
            take_profit REAL,
            peak_price REAL,
            trailing_active INTEGER,
            last_update TIMESTAMP,
            source TEXT,
            notes TEXT,
            usdc_spent REAL DEFAULT 0,
            entry_liquidity REAL DEFAULT 0,
            last_liquidity_check TEXT
        )
    """)

    # -----------------------
    # AI boot log
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_boot_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP,
            message TEXT
        )
    """)

    # -----------------------
    # AI thought signals
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_thought (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract TEXT,
            decision INTEGER,
            time_queued TIMESTAMP,
            trade_stat TEXT,
            last_price REAL,
            token TEXT,
            symbol TEXT,
            pair_id TEXT,
            price REAL,
            marketcap TEXT,
            liquidity TEXT,
            fdv TEXT,
            in_price REAL,
            last_price_older REAL,
            time_inprice TIMESTAMP
        )
    """)

    # -----------------------
    # Transaction book
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transaction_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract TEXT,
            decision INTEGER,
            time_executed TIMESTAMP,
            tx_hash TEXT
        )
    """)

    # -----------------------
    # Pending trades
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract TEXT,
            decision INTEGER,
            time_queued TIMESTAMP
        )
    """)

    # -----------------------
    # Wallet snapshots
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT NOT NULL,
            sol_balance   REAL,
            sol_usd       REAL,
            usdc_balance  REAL,
            total_usd     REAL,
            fees_accum_usd REAL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_tokens (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id   INTEGER NOT NULL REFERENCES wallet_snapshots(id),
            token_mint    TEXT,
            token_amount  REAL,
            token_decimals INTEGER,
            token_usd_value REAL
        )
    """)

    # -----------------------
    # Allocation slots
    # -----------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS allocation_slots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id         INTEGER NOT NULL,
            slot_type       TEXT NOT NULL,
            start_timestamp TEXT NOT NULL,
            stop_timestamp  TEXT NOT NULL,
            allocation_usd  REAL NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Initialized successfully at {DB_PATH}")


if __name__ == "__main__":
    init_db()
