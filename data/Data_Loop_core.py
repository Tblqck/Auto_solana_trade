# Datacore.py
import datetime
import requests
import time
import yaml

from core.db_utils import get_db_connection

# ----------------------------
# Load config.yaml
# ----------------------------
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

MAX_CANDLES = 1000    # GeckoTerminal hard limit per request
RETRY_WAIT = config.get("retry_wait_seconds", 7)
LOOP_INTERVAL = config.get("loop_interval_seconds", 20)

# ----------------------------
# Module control helpers
# ----------------------------
def set_module_on(module_name: str):
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name=?", (module_name,))
    row = cur.fetchone()
    conn.close()
    return True if (row is None or row[0].upper() == "ON") else False


def update_module_status(module_name: str):
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


# ----------------------------
# DB helpers
# ----------------------------
def get_pairs():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT pair_id FROM supported_tokens WHERE pair_id IS NOT NULL")
    pairs = [row[0] for row in cur.fetchall() if row[0]]
    conn.close()
    return pairs


def get_last_timestamp(pair_id: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT MAX(time) FROM ohlc_data WHERE pair_id=?", (pair_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row and row[0] else None


def _parse_ts(val):
    if isinstance(val, datetime.datetime):
        dt = val
    else:
        dt = datetime.datetime.fromisoformat(str(val))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


# ----------------------------
# API fetch
# ----------------------------
def fetch_recent_ohlc_gecko(pair_id: str, limit=MAX_CANDLES, retries=3):
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair_id}/ohlcv/minute"
    for _ in range(retries):
        try:
            res = requests.get(url, params={"limit": limit}, timeout=15)
        except Exception as e:
            print(f"[ERROR] Request error for {pair_id}: {e}")
            time.sleep(RETRY_WAIT)
            continue

        if res.status_code == 429:
            print(f"[WARN] Rate limit hit for {pair_id}, waiting {RETRY_WAIT}s...")
            time.sleep(RETRY_WAIT)
            continue

        if res.status_code != 200:
            print(f"[ERROR] {res.status_code} for {pair_id}")
            return []

        return res.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])

    return []


# ----------------------------
# Gap fill
# ----------------------------
def fill_gaps(candles):
    """
    Forward-fill missing minutes between sparse candles.
    Each gap minute gets open=high=low=close=last_close, volume=0.
    Input candles are [ts_unix_seconds, o, h, l, c, v].
    """
    if not candles:
        return candles

    candles = sorted(candles, key=lambda x: x[0])
    filled = []

    for i, candle in enumerate(candles):
        filled.append(candle)
        if i == len(candles) - 1:
            break

        cur_ts = candles[i][0]
        next_ts = candles[i + 1][0]
        last_close = candles[i][4]

        # fill every missing 60-second slot between this candle and the next
        while next_ts - cur_ts > 60:
            cur_ts += 60
            filled.append([cur_ts, last_close, last_close, last_close, last_close, 0])

    return filled


# ----------------------------
# DB write
# ----------------------------
def save_ohlc_data(pair_id, candles):
    if not candles:
        return 0
    conn = get_db_connection()
    cur = conn.cursor()
    rows = []
    for c in candles:
        ts, o, h, l, close, v = c[0], c[1], c[2], c[3], c[4], c[5]
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        rows.append((pair_id, dt, o, h, l, close, v))
    cur.executemany("""
        INSERT OR IGNORE INTO ohlc_data(pair_id, time, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    inserted = cur.rowcount
    conn.close()
    return inserted


# ----------------------------
# Main callable function
# ----------------------------
def run_data_loop() -> dict:
    """
    One full pass: fetch OHLC for every pair, gap-fill missing minutes,
    insert new rows into ohlc_data.
    Returns {"pairs_checked": N, "rows_inserted": N} for the hourly digest.
    """
    set_module_on("DataLoop")

    pairs = get_pairs()
    if not pairs:
        print("[INFO] No pairs found in DB. Exiting.")
        _turn_module_off("DataLoop")
        return {"pairs_checked": 0, "rows_inserted": 0}

    print(f"[INFO] Found {len(pairs)} pairs to update.")

    pairs_checked = 0
    rows_inserted = 0

    for pair_id in pairs:
        if not is_module_on("DataLoop"):
            print("[INFO] DataLoop turned OFF mid-run. Stopping.")
            break

        last_time = get_last_timestamp(pair_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        if last_time:
            last_dt = _parse_ts(last_time)
            minutes_missing = max(0, int((now - last_dt).total_seconds() / 60))
        else:
            minutes_missing = MAX_CANDLES

        if minutes_missing == 0:
            print(f"[SKIP] {pair_id} already up to date.")
            pairs_checked += 1
            continue

        limit = min(minutes_missing, MAX_CANDLES)
        print(f"[FETCH] {pair_id}: {minutes_missing} min missing -> fetching {limit}")

        candles = fetch_recent_ohlc_gecko(pair_id, limit=limit)
        if not candles:
            print(f"[WARN] No data returned for {pair_id}")
            pairs_checked += 1
            continue

        raw_count = len(candles)
        candles = fill_gaps(candles)
        gap_filled = len(candles) - raw_count

        inserted = save_ohlc_data(pair_id, candles)
        print(f"[OK] {pair_id}: fetched {raw_count}, gap-filled +{gap_filled}, inserted {inserted}")

        pairs_checked += 1
        rows_inserted += inserted

        update_module_status("DataLoop")
        time.sleep(1)

    print("[DONE] DataLoop finished one rotation.")
    _turn_module_off("DataLoop")

    stats = {"pairs_checked": pairs_checked, "rows_inserted": rows_inserted}

    try:
        from notify.reports import accumulate_dataloop_stats
        from notify.telegram import send
        accumulate_dataloop_stats(pairs_checked, rows_inserted)
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M UTC")
        send(
            f"<b>DataLoop cycle complete — {now_str}</b>\n"
            f"Pairs checked: {pairs_checked}\n"
            f"New OHLC rows: {rows_inserted}"
        )
    except Exception as e:
        print(f"[Notify] DataLoop notify failed (non-fatal): {e}")

    return stats


# ----------------------------
# Allow standalone execution
# ----------------------------
if __name__ == "__main__":
    run_data_loop()
