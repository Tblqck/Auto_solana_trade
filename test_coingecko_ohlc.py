import requests
import datetime
import time
from collections import defaultdict
from core.db_utils import get_db_connection

# =========================================================
# CONFIG
# =========================================================

NETWORK = "solana"
BASE_URL = "https://api.geckoterminal.com/api/v2"

COINGECKO_LIST = None


# =========================================================
# COINGECKO SECTION
# =========================================================

def load_coingecko_list():
    global COINGECKO_LIST

    if COINGECKO_LIST is None:
        print("Loading CoinGecko coin list...")
        url = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
        COINGECKO_LIST = requests.get(url, timeout=20).json()

    return COINGECKO_LIST


def find_coingecko_id(contract, network="solana"):

    coins = load_coingecko_list()

    for coin in coins:
        platforms = coin.get("platforms", {})

        if platforms.get(network):
            if platforms[network].lower() == contract.lower():
                return coin["id"]

    return None


def fetch_coingecko_ohlc(coin_id, days=1):

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"

    params = {
        "vs_currency": "usd",
        "days": days
    }

    try:
        res = requests.get(url, params=params, timeout=15)

        if res.status_code != 200:
            return None

        data = res.json()

        # 🔥 FIX: normalize to 6 fields (add volume=None)
        normalized = []
        for row in data:
            if len(row) == 5:
                ts, o, h, l, c = row
                normalized.append([ts, o, h, l, c, None])

        return normalized

    except Exception as e:
        print("CoinGecko error:", e)
        return None


# =========================================================
# GECKOTERMINAL SECTION
# =========================================================

def fetch_gecko_ohlcv(pair_id, retries=3):

    url = f"{BASE_URL}/networks/{NETWORK}/pools/{pair_id}/ohlcv/minute"

    try:
        res = requests.get(url, timeout=15)

        if res.status_code == 429:
            if retries > 0:
                print("⚠ Rate limited, retrying...")
                time.sleep(5)
                return fetch_gecko_ohlcv(pair_id, retries - 1)
            return None

        if res.status_code != 200:
            return None

        data = res.json()
        return data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])

    except Exception as e:
        print("GeckoTerminal error:", e)
        return None


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_gecko(candles):

    grouped = defaultdict(list)

    for ts, o, h, l, c, v in candles:
        grouped[ts].append((o, h, l, c, v))

    clean = []

    for ts in sorted(grouped.keys()):
        group = grouped[ts]

        clean.append([
            ts * 1000,  # 🔥 convert seconds → ms
            group[0][0],
            max(x[1] for x in group),
            min(x[2] for x in group),
            group[-1][3],
            sum(x[4] for x in group)
        ])

    return clean


def fill_missing_minutes(candles):

    candles = sorted(candles, key=lambda x: x[0])
    filled = []

    for i in range(len(candles)):
        filled.append(candles[i])

        if i == len(candles) - 1:
            break

        cur = candles[i][0]
        nxt = candles[i + 1][0]

        while nxt - cur > 60000:
            cur += 60000
            last_close = filled[-1][4]

            filled.append([
                cur,
                last_close,
                last_close,
                last_close,
                last_close,
                0
            ])

    return filled


# =========================================================
# DATABASE
# =========================================================

def save_ohlc(pair_id, rows):

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ohlc_data (
            pair_id TEXT,
            time TIMESTAMP,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (pair_id, time)
        )
    """)

    count = 0

    for row in rows:

        # 🔥 DOUBLE SAFETY (handles any format)
        if len(row) == 5:
            ts, o, h, l, c = row
            v = None
        elif len(row) == 6:
            ts, o, h, l, c, v = row
        else:
            print("⚠ Bad row format:", row)
            continue

        # 🔥 FIX timestamp (ms vs sec)
        if ts > 1e12:
            dt = datetime.datetime.fromtimestamp(ts / 1000)
        else:
            dt = datetime.datetime.fromtimestamp(ts)

        try:
            cur.execute("""
                INSERT OR REPLACE INTO ohlc_data
                (pair_id, time, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pair_id, dt, o, h, l, c, v))

            count += 1

        except Exception as e:
            print("DB error:", e)

    conn.commit()
    conn.close()

    return count


# =========================================================
# MAIN PIPELINE
# =========================================================

def process_token(contract, pair_id):

    print(f"\nProcessing {contract}")

    # 1️⃣ Try CoinGecko
    coin_id = find_coingecko_id(contract)

    if coin_id:
        print(f"Using CoinGecko: {coin_id}")

        ohlc = fetch_coingecko_ohlc(coin_id)

        if ohlc:
            saved = save_ohlc(pair_id, ohlc)
            print(f"Saved {saved} rows (CoinGecko)")
            return True

    # 2️⃣ Fallback to GeckoTerminal
    print("Falling back to GeckoTerminal...")

    candles = fetch_gecko_ohlcv(pair_id)

    if not candles:
        print("No data available")
        return False

    candles = normalize_gecko(candles)
    candles = fill_missing_minutes(candles)

    saved = save_ohlc(pair_id, candles)

    print(f"Saved {saved} rows (GeckoTerminal)")
    return True


# =========================================0================
# ENTRY
# =========================================================

if __name__ == "__main__":

    tokens = [
        {
            "contract": "So11111111111111111111111111111111111111112",
            "pair_id": "your_real_pair_id_here"
        }
    ]

    for t in tokens:
        process_token(t["contract"], t["pair_id"])
        time.sleep(2)