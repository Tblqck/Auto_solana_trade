from datetime import datetime, timezone
import time
import json

from db_utils import get_db_connection
from trade_executor import run_trades  # silent executor returning (success, failed)
from trade_2 import build_trade_signals  # dynamic trade signal builder
from wallet_state import get_wallet_state, save_wallet_csv  # wallet monitoring

# ===========================
# DB LOCK
# ===========================
def acquire_lock():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control (module_name, status)
        VALUES ('trade_engine', 'ON')
        ON CONFLICT(module_name)
        DO UPDATE SET status='ON'
        WHERE module_control.status='OFF'
    """)
    conn.commit()
    cur.execute("SELECT status FROM module_control WHERE module_name='trade_engine'")
    row = cur.fetchone()
    conn.close()
    return row and row[0] == "ON"

def release_lock():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE module_control
        SET status='OFF'
        WHERE module_name='trade_engine'
        AND status='ON'
    """)
    conn.commit()
    conn.close()

# ===========================
# DB HELPERS
# ===========================
def remove_pending(ids):
    if not ids:
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.executemany("DELETE FROM pending_trades WHERE id=?", [(i,) for i in ids])
    conn.commit()
    conn.close()

def insert_live_trade(contract, entry_price):
    """Insert a new live trade into the DB"""
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc)
    cur.execute("""
        INSERT OR REPLACE INTO live_trades (
            contract, entry_price, entry_time,
            status, decision, peak_price, trailing_active, last_update
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (contract, entry_price, now, "OPEN", 1, entry_price, 0, now))
    conn.commit()
    conn.close()

def remove_live_trade(contract):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM live_trades WHERE contract=?", (contract,))
    conn.commit()
    conn.close()

def map_pending_ids():
    """Return a dict mapping contract -> pending id"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, contract FROM pending_trades")
    mapping = {row[1]: row[0] for row in cur.fetchall()}
    conn.close()
    return mapping

# ===========================
# MAIN ENGINE
# ===========================
def run_trade_engine():
    if not acquire_lock():
        print("⚠️ Trade engine already running. Exiting.")
        return

    fees_accum = 0  # track accumulated fees if needed

    try:
        # Step 1: Build trade signals
        trade_signals = build_trade_signals()
        if not trade_signals:
            print("🔹 No trades to execute.")
            return

        # Map contracts -> pending ids
        pending_map = map_pending_ids()

        # Step 2: Execute trades
        try:
            successful_signals, failed_signals = run_trades(trade_signals)
        except Exception as e:
            print(f"⚠️ Trade execution failed: {e}")
            return

        # Step 3: Remove successful trades from pending
        ids_to_remove = [
            pending_map.get(s["token_mint"])
            for s in successful_signals
            if pending_map.get(s["token_mint"])
        ]
        remove_pending(ids_to_remove)

        # Step 4: Apply DB side effects
        for s in successful_signals:
            if s["type"] == "BUY":
                insert_live_trade(s["token_mint"], entry_price=0)
            elif s["type"] == "SELL":
                remove_live_trade(s["token_mint"])

        # Step 5: Update wallet snapshot CSV
        try:
            wallet_state = get_wallet_state()
            save_wallet_csv(wallet_state, fees_accum)
        except Exception as e:
            print(f"⚠️ Wallet snapshot failed: {e}")

        # Logging summary
        print("🔹 Batch execution complete")
        print(f"✅ Successful trades: {successful_signals}")
        print(f"⚠️ Failed trades: {failed_signals}")

    finally:
        release_lock()

# ===========================
# ENTRY
# ===========================
if __name__ == "__main__":
    RUN_CONTINUOUSLY = False  # set False if you want just one run
    if RUN_CONTINUOUSLY:
        while True:
            print(f"📊 Running trade engine at {datetime.utcnow().isoformat()} UTC")
            run_trade_engine()
            time.sleep(10)
    else:
        run_trade_engine()
