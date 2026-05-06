# db_tokens.py
import sqlite3
import os

DB_PATH = os.path.join("db_files", "dex_pipeline.db")


# -----------------------
# DB Connection
# -----------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------
# Check Column Exists
# -----------------------
def column_exists(table, column):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cur.fetchall()]

    conn.close()
    return column in columns


# -----------------------
# Ensure supported_tokens is usable
# -----------------------
def ensure_supported_tokens():
    conn = get_db_connection()
    cur = conn.cursor()

    # Create table if missing
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

    # Add created_at if missing (future-proof)
    if not column_exists("supported_tokens", "created_at"):
        try:
            cur.execute("""
                ALTER TABLE supported_tokens
                ADD COLUMN created_at TIMESTAMP
            """)

            cur.execute("""
                UPDATE supported_tokens
                SET created_at = CURRENT_TIMESTAMP
                WHERE created_at IS NULL
            """)

            print("✅ created_at added to supported_tokens")

        except sqlite3.OperationalError:
            pass

    # Index for speed
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_supported_contract
        ON supported_tokens(contract)
    """)

    conn.commit()
    conn.close()


# -----------------------
# Get ALL supported tokens
# -----------------------
def get_supported_tokens(limit=None):
    conn = get_db_connection()
    cur = conn.cursor()

    query = "SELECT * FROM supported_tokens"

    if limit:
        query += " LIMIT ?"
        cur.execute(query, (limit,))
    else:
        cur.execute(query)

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# -----------------------
# Get LAST tokens (safe)
# -----------------------
def get_last_supported_tokens(n=2):
    conn = get_db_connection()
    cur = conn.cursor()

    # Prefer created_at if exists
    if column_exists("supported_tokens", "created_at"):
        cur.execute(f"""
            SELECT *
            FROM supported_tokens
            ORDER BY created_at DESC
            LIMIT {n}
        """)
    else:
        # fallback
        cur.execute(f"""
            SELECT *
            FROM supported_tokens
            ORDER BY rowid DESC
            LIMIT {n}
        """)

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# -----------------------
# Get tokens for OHLC fetch
# -----------------------
def get_tokens_for_ohlc(limit=50):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT contract, pair_id
        FROM supported_tokens
        WHERE pair_id IS NOT NULL
        LIMIT ?
    """, (limit,))

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


# -----------------------
# Insert / Update supported token
# -----------------------
def insert_supported_token(data: dict):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO supported_tokens (
            contract, token, symbol, pair_id,
            price, marketcap, liquidity, fdv, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(contract) DO UPDATE SET
            token=excluded.token,
            symbol=excluded.symbol,
            pair_id=excluded.pair_id,
            price=excluded.price,
            marketcap=excluded.marketcap,
            liquidity=excluded.liquidity,
            fdv=excluded.fdv,
            created_at=CURRENT_TIMESTAMP
    """, (
        data.get("contract"),
        data.get("token"),
        data.get("symbol"),
        data.get("pair_id"),
        data.get("price"),
        data.get("marketcap"),
        data.get("liquidity"),
        data.get("fdv"),
    ))

    conn.commit()
    conn.close()


# -----------------------
# TEST RUN
# -----------------------
if __name__ == "__main__":
    ensure_supported_tokens()

    # Example insert
    insert_supported_token({
        "contract": "test123",
        "token": "Test Token",
        "symbol": "TT",
        "pair_id": "pair_test",
        "price": "0.02",
        "marketcap": "$200K",
        "liquidity": "$50K",
        "fdv": "$500K"
    })

    print("\nALL TOKENS:")
    print(get_supported_tokens())

    print("\nLAST 2 TOKENS:")
    print(get_last_supported_tokens())

    print("\nTOKENS FOR OHLC:")
    print(get_tokens_for_ohlc(5))