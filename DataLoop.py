# DataLoop.py
import os
import pandas as pd
import datetime
import requests
import yaml
import time

MASTER_FILE = "master_control.csv"
STATUS_FILE = "dataloop_status.csv"


# ----------------------------
# Helpers
# ----------------------------
def is_module_on(module_name: str) -> bool:
    """Check master_control.csv for module ON/OFF state."""
    if not os.path.exists(MASTER_FILE):
        return True  # default ON if missing
    df = pd.read_csv(MASTER_FILE)
    if module_name not in df.columns:
        return True
    return df[module_name].iloc[0].strip().upper() == "ON"


def update_status():
    """Write last_run timestamp to dataloop_status.csv."""
    now = datetime.datetime.now(datetime.UTC).isoformat()
    pd.DataFrame([{"last_run": now}]).to_csv(STATUS_FILE, index=False)


# ----------------------------
# Load config.yaml
# ----------------------------
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

OHLC_CSV_BASE = config["ohlc_csv"]
PAIR_CSV = config.get("pair_csv", "filtered_contracts.csv")
MAX_FETCH = config.get("max_fetch_minutes", 200)
RETRY_WAIT = config.get("retry_wait_seconds", 7)
LOOP_INTERVAL = 20


# ----------------------------
# Fetch OHLC with pagination
# ----------------------------
def fetch_recent_ohlc_gecko(pair_id: str, interval="minute", page=1, limit=200, retries=3, wait_seconds=RETRY_WAIT):
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair_id}/ohlcv/{interval}"
    for attempt in range(retries):
        try:
            res = requests.get(url, params={"limit": limit, "page": page})
        except Exception as e:
            print(f"❌ Exception fetching {pair_id} page {page}: {e}")
            time.sleep(wait_seconds)
            continue

        if res.status_code == 429:
            print(f"⚠️ Rate limit hit for {pair_id}, waiting {wait_seconds}s...")
            time.sleep(wait_seconds)
            continue

        if res.status_code != 200:
            print(f"❌ Error {res.status_code} for {pair_id}: {res.text}")
            return pd.DataFrame()

        candles = res.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame([{
            "pair_id": pair_id,
            "time": datetime.datetime.fromtimestamp(c[0], tz=datetime.UTC),
            "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]
        } for c in candles])

        return df.sort_values("time").reset_index(drop=True)

    return pd.DataFrame()


# ----------------------------
# Summarize missing candles
# ----------------------------
def summarize_missing(ohlc_csv: str):
    if not os.path.exists(ohlc_csv):
        return pd.DataFrame()

    df = pd.read_csv(ohlc_csv)
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df = df.dropna(subset=["time"]).drop_duplicates(subset=["pair_id", "time"])
    df = df.sort_values(["pair_id", "time"]).reset_index(drop=True)

    now = datetime.datetime.now(datetime.UTC).replace(second=0, microsecond=0)
    results = []
    for pid, group in df.groupby("pair_id"):
        last_time = group["time"].max()
        delta = now - last_time
        results.append({
            "pair_id": pid,
            "last_timestamp": last_time,
            "minutes_missing": max(0, int(delta.total_seconds() / 60)),
        })
    return pd.DataFrame(results).sort_values("minutes_missing", ascending=False)


# ----------------------------
# Runner
# ----------------------------
if __name__ == "__main__":
    while True:
        if not is_module_on("DataLoop"):
            print("⏹️ DataLoop OFF in master_control.csv. Exiting.")
            break

        if not os.path.exists(PAIR_CSV):
            raise FileNotFoundError(f"❌ Pair CSV not found: {PAIR_CSV}")

        pairs_df = pd.read_csv(PAIR_CSV)
        if "PairId" not in pairs_df.columns:
            raise ValueError("❌ Pair CSV must have a 'PairId' column")

        df_summary = summarize_missing(OHLC_CSV_BASE)
        existing_pairs = set(df_summary["pair_id"]) if not df_summary.empty else set()

        print("\n📊 Missing Candle Summary:")
        print(df_summary.head(20))

        for pair_id in pairs_df["PairId"].dropna().unique():
            if not is_module_on("DataLoop"):
                print("⏹️ DataLoop turned OFF mid-run. Stopping.")
                break

            minutes_missing = MAX_FETCH if pair_id not in existing_pairs else \
                df_summary[df_summary["pair_id"] == pair_id].iloc[0]["minutes_missing"]

            if minutes_missing == 0:
                print(f"⏭️ {pair_id} is already up to date.")
                continue

            print(f"\n🔎 {pair_id}: Missing {minutes_missing} min, fetching...")
            to_fetch, page, df_all = minutes_missing, 1, []

            while to_fetch > 0:
                fetch_size = min(MAX_FETCH, to_fetch)
                df_page = fetch_recent_ohlc_gecko(pair_id, page=page, limit=fetch_size)

                if df_page.empty:
                    print(f"⚠️ No more data returned for {pair_id} (page {page}).")
                    break

                df_all.append(df_page)
                to_fetch -= fetch_size
                page += 1
                time.sleep(0.25)

                if len(df_page) < fetch_size:
                    break

            if df_all:
                df_new = pd.concat(df_all, ignore_index=True).drop_duplicates(subset=["pair_id", "time"])
                df_new = df_new.sort_values("time")

                if os.path.exists(OHLC_CSV_BASE):
                    df_existing = pd.read_csv(OHLC_CSV_BASE)
                    df_existing["time"] = pd.to_datetime(df_existing["time"], utc=True, errors="coerce")
                    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                    df_combined = df_combined.drop_duplicates(subset=["pair_id", "time"]).sort_values(["pair_id", "time"])
                    df_combined.to_csv(OHLC_CSV_BASE, index=False)
                    print(f"✅ Updated {pair_id}: +{len(df_new)} candles, total {len(df_combined)} rows")
                else:
                    df_new.to_csv(OHLC_CSV_BASE, index=False)
                    print(f"✅ Created {OHLC_CSV_BASE} with {len(df_new)} rows for {pair_id}")
            else:
                print(f"⚠️ No data fetched for {pair_id}")

        # Mark status done for this loop
        update_status()
        print("📌 DataLoop finished one rotation.")

        # Sleep until next run
        time.sleep(LOOP_INTERVAL)
