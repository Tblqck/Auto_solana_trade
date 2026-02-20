# DataLoop_DB.py
import sqlite3
import datetime
import requests
import time
import yaml

from db_utils import get_db_connection  # your DB helper

# ----------------------------
# Load config.yaml
# ----------------------------
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

MAX_FETCH = config.get("max_fetch_minutes", 200)
RETRY_WAIT = config.get("retry_wait_seconds", 7)
LOOP_INTERVAL = config.get("loop_interval_seconds", 20)

# ----------------------------
# Helpers
# ----------------------------
def set_module_on(module_name: str):
    """Set a module in module_control to ON."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control(module_name, status)
        VALUES (?, 'ON')
        ON CONFLICT(module_name) DO UPDATE SET status='ON'
    """, (module_name,))
    conn.commit()
    conn.close()


def _turn_module_off(module_name: str):
    """Set a module in module_control to OFF."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control(module_name, status)
        VALUES (?, 'OFF')
        ON CONFLICT(module_name) DO UPDATE SET status='OFF'
    """, (module_name,))
    conn.commit()
    conn.close()


def is_module_on(module_name: str) -> bool:
    """Check module status from DB table module_control."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (module_name,))
    row = cur.fetchone()
    conn.close()
    return True if (row is None or row[0].upper() == "ON") else False


def update_module_status(module_name: str):
    """Update last_run timestamp in module_status table."""
    now = datetime.datetime.now(datetime.timezone.utc)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_status(module_name, last_run)
        VALUES(?, ?)
        ON CONFLICT(module_name) DO UPDATE SET last_run=excluded.last_run
    """, (module_name, now))
    conn.commit()
    conn.close()


def get_pairs():
    """Return all PairIds from supported_tokens table."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT PairId FROM supported_tokens")
    pairs = [row[0] for row in cur.fetchall() if row[0]]
    conn.close()
    return pairs


def fetch_recent_ohlc_gecko(pair_id: str, interval="minute", page=1, limit=200, retries=3):
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair_id}/ohlcv/{interval}"
    for attempt in range(retries):
        try:
            res = requests.get(url, params={"limit": limit, "page": page})
        except Exception as e:
            print(f"❌ Exception fetching {pair_id} page {page}: {e}")
            time.sleep(RETRY_WAIT)
            continue

        if res.status_code == 429:
            print(f"⚠️ Rate limit hit for {pair_id}, waiting {RETRY_WAIT}s...")
            time.sleep(RETRY_WAIT)
            continue

        if res.status_code != 200:
            print(f"❌ Error {res.status_code} for {pair_id}: {res.text}")
            return []

        candles = res.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        if not candles:
            return []

        df = [{
            "pair_id": pair_id,
            "time": datetime.datetime.fromtimestamp(c[0], tz=datetime.timezone.utc),
            "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]
        } for c in candles]

        return df
    return []


def get_last_timestamp(pair_id: str):
    """Get the last timestamp stored for a pair."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT MAX(time) FROM ohlc_data WHERE pair_id=?", (pair_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def save_ohlc_data(df):
    """Insert OHLC data into ohlc_data table."""
    if not df:
        return 0
    conn = get_db_connection()
    cur = conn.cursor()
    rows = [(d["pair_id"], d["time"], d["open"], d["high"], d["low"], d["close"], d["volume"]) for d in df]
    cur.executemany("""
        INSERT OR IGNORE INTO ohlc_data(pair_id, time, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()
    return len(rows)


# ----------------------------
# Main callable function
# ----------------------------
def run_data_loop():
    """
    Run one full iteration of DataLoop (fetch all pairs once).
    Updates module_status per pair and turns DataLoop OFF after completion.
    """
    
    # Make sure DataLoop module is ON
    set_module_on("DataLoop")

    if not is_module_on("DataLoop"):
        print("⏹️ DataLoop OFF in DB. Exiting.")
        return

    pairs = get_pairs()
    if not pairs:
        print("❌ No pairs found in DB. Exiting.")
        _turn_module_off("DataLoop")
        return

    print(f"\n📊 Found {len(pairs)} pairs to update.")

    for pair_id in pairs:
        if not is_module_on("DataLoop"):
            print("⏹️ DataLoop turned OFF mid-run. Stopping.")
            break

        last_time = get_last_timestamp(pair_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        minutes_missing = MAX_FETCH if not last_time else max(
            0, int((now - datetime.datetime.fromisoformat(last_time)).total_seconds() / 60)
        )

        if minutes_missing == 0:
            print(f"⏭️ {pair_id} is already up to date.")
            continue

        print(f"\n🔎 {pair_id}: Missing {minutes_missing} min, fetching...")
        to_fetch, page, df_all = minutes_missing, 1, []

        while to_fetch > 0:
            fetch_size = min(MAX_FETCH, to_fetch)
            df_page = fetch_recent_ohlc_gecko(pair_id, page=page, limit=fetch_size)
            if not df_page:
                print(f"⚠️ No more data returned for {pair_id} (page {page}).")
                break
            df_all.extend(df_page)
            to_fetch -= fetch_size
            page += 1
            time.sleep(0.25)
            if len(df_page) < fetch_size:
                break

        inserted = save_ohlc_data(df_all)
        print(f"✅ Inserted {inserted} rows for {pair_id}")

        # Update last_run for DataLoop after each pair fetch
        update_module_status("DataLoop")

    print("📌 DataLoop finished one rotation.")

    # Turn DataLoop OFF automatically
    _turn_module_off("DataLoop")
    print("⏹️ DataLoop module turned OFF in module_control.")


# ----------------------------
# Allow standalone execution
# ----------------------------
if __name__ == "__main__":
    run_data_loop()
