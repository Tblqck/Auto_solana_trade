import os
import time
import datetime
import requests
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from seleniumbase import Driver

# -------------------------
# Utility Functions
# -------------------------

def processDataRaw(data):
    """Clean raw scraped data into a DataFrame."""
    clean_data = [x for x in data if x not in ['V1', 'V2', 'V3']]
    rows, current_row = [], []
    for item in clean_data:
        if item.startswith("#") and current_row:
            rows.append(current_row)
            current_row = []
        current_row.append(item)
    if current_row:
        rows.append(current_row)
    return pd.DataFrame(rows)

def rearrange_df(df):
    """Extract Column 5 with token names."""
    df = df.drop(index=0).reset_index(drop=True)
    for idx, row in df.iterrows():
        try:
            col4 = str(row[4]) if 4 in row else ""
            col5 = str(row[5]) if 5 in row else ""
            col6 = str(row[6]) if 6 in row else ""
            if col4 != "SOL":
                if not col6.startswith("$"):
                    df.at[idx, 5] = col4
                else:
                    df.at[idx, 5] = col4
        except Exception as e:
            print(f"Error processing row {idx}: {e}")
    return pd.DataFrame({"Column5": df[5]})

def scrapeDex():
    """Scrape Dexscreener trending tokens."""
    url = "https://dexscreener.com/solana/5m?rankBy=trendingScoreM5&order=desc"
    driver = Driver(uc=True, headless=True)
    rearranged_df = None
    try:
        driver.get(url)
        data_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'ds-dex-table'))
        )
        if data_element:
            data = data_element.text.split('\n')
            original_df = processDataRaw(data)
            rearranged_df = rearrange_df(original_df)
    except Exception as e:
        print(f"Exception during scraping: {e}")
    driver.quit()
    return rearranged_df

def human_format(num):
    """Convert large numbers into K, M, B style strings."""
    if num is None:
        return None
    num = float(num)
    if num >= 1e9:
        return f"${num/1e9:.1f}B"
    elif num >= 1e6:
        return f"${num/1e6:.1f}M"
    elif num >= 1e3:
        return f"${num/1e3:.0f}K"
    else:
        return f"${num:.0f}"

def get_best_pair(token_name, min_mcap=140_000, min_liquidity=100_000):
    """Fetch best trading pair for a token from Dexscreener API."""
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={token_name}"
        resp = requests.get(url, timeout=10).json()
        if "pairs" not in resp or len(resp["pairs"]) == 0:
            return None

        valid_pairs = []
        for pair in resp["pairs"]:
            try:
                mcap = pair.get("marketCap", 0) or 0
                liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
                fdv = pair.get("fdv", 0) or 0
                if mcap >= min_mcap and liquidity >= min_liquidity:
                    valid_pairs.append({
                        "Token": pair["baseToken"]["name"],
                        "Symbol": pair["baseToken"]["symbol"],
                        "Contract": pair["baseToken"]["address"],
                        "PairId": pair.get("pairAddress"),
                        "Price": f"${float(pair.get('priceUsd', 0)):.6f}",
                        "MarketCap_raw": mcap,
                        "Liquidity_raw": liquidity,
                        "FDV_raw": fdv,
                        "MarketCap": human_format(mcap),
                        "Liquidity": human_format(liquidity),
                        "FDV": human_format(fdv),
                    })
            except Exception as e:
                print(f"Error parsing pair for {token_name}: {e}")

        if not valid_pairs:
            return None
        best_pair = max(valid_pairs, key=lambda x: (x["MarketCap_raw"], x["Liquidity_raw"]))
        return {
            "Token": best_pair["Token"],
            "Symbol": best_pair["Symbol"],
            "Contract": best_pair["Contract"],
            "PairId": best_pair["PairId"],
            "Price": best_pair["Price"],
            "MarketCap": best_pair["MarketCap"],
            "Liquidity": best_pair["Liquidity"],
            "FDV": best_pair["FDV"],
        }
    except Exception as e:
        print(f"Error fetching pairs for {token_name}: {e}")
        return None

def add_contracts_to_df(rearranged_df):
    """Add contracts and market data to tokens dataframe."""
    results = []
    for token in rearranged_df["Column5"]:
        best_pair = get_best_pair(token)
        if best_pair:
            results.append(best_pair)
        time.sleep(0.5)
    return pd.DataFrame(results)

def filter_supported_by_jupiter(df, contract_col="Contract", batch_size=50, price_api_url="https://lite-api.jup.ag/price/v3"):
    """Filter tokens tradable on Jupiter."""
    supported = []
    contracts = df[contract_col].dropna().unique().tolist()
    for i in range(0, len(contracts), batch_size):
        batch = contracts[i:i + batch_size]
        ids = ",".join(batch)
        resp = requests.get(price_api_url, params={"ids": ids})
        if resp.status_code != 200:
            print(f"Error querying Jupiter API for batch starting at {i}: {resp.status_code}")
            continue
        data = resp.json()
        supported.extend(data.keys())
    supported_set = set(supported)
    filtered_df = df[df[contract_col].isin(supported_set)].copy()
    return filtered_df, supported_set

def fetch_full_ohlc_gecko(pair_id: str, interval="hour", pages=5, limit=200, sleep=0.5, output_csv=None):
    """Fetch OHLCV candles from GeckoTerminal API."""
    all_candles = []
    for page in range(1, pages + 1):
        url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair_id}/ohlcv/{interval}?limit={limit}&page={page}"
        res = requests.get(url)
        if res.status_code == 429:
            print(f"⚠️ Rate limit hit for {pair_id} page {page}, waiting 7s...")
            time.sleep(7)
            continue
        if res.status_code != 200:
            print(f"❌ Error {res.status_code} for {pair_id} page {page}: {res.text}")
            return pd.DataFrame()
        candles = res.json().get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        if not candles:
            break
        for c in candles:
            all_candles.append({
                "pair_id": pair_id,
                "time": datetime.datetime.fromtimestamp(c[0]),
                "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5],
            })
        time.sleep(sleep)

    df = pd.DataFrame(all_candles)
    if not df.empty:
        df = df.drop_duplicates(subset=["pair_id", "time"]).sort_values(["pair_id", "time"]).reset_index(drop=True)
        if output_csv:
            df.to_csv(output_csv, mode="a", header=not os.path.exists(output_csv), index=False)
    return df

def fetch_and_save_all(contract_df, interval="minute", pages=10, limit=200, output_csv="all_pairs_ohlc.csv", fetched_pairs_csv="fetched_pairs.csv", filtered_contracts_csv="filtered_contracts.csv"):
    """Fetch OHLC for all pairs and save progressively (resumable)."""
    if os.path.exists(fetched_pairs_csv):
        fetched_pairs_df = pd.read_csv(fetched_pairs_csv)
        fetched_pairs = set(fetched_pairs_df["PairId"].dropna().unique())
    else:
        fetched_pairs, fetched_pairs_df = set(), pd.DataFrame(columns=["PairId"])
    new_fetched_pairs = []

    for pair_id in contract_df["PairId"].dropna().unique():
        if pair_id in fetched_pairs:
            print(f"⏩ Skipping {pair_id} (already fetched)")
            continue
        print(f"\n📊 Fetching Pair ID: {pair_id}")
        df = fetch_full_ohlc_gecko(pair_id, interval=interval, pages=pages, limit=limit, output_csv=output_csv)
        if not df.empty:
            new_fetched_pairs.append(pair_id)
        else:
            print(f"⚠️ Skipped {pair_id} (no data)")

    if new_fetched_pairs:
        pd.DataFrame(new_fetched_pairs, columns=["PairId"]).to_csv(fetched_pairs_csv, mode="a", header=not os.path.exists(fetched_pairs_csv), index=False)

    fetched_pairs_df = pd.read_csv(fetched_pairs_csv).drop_duplicates()
    filtered_df = contract_df[contract_df["PairId"].isin(fetched_pairs_df["PairId"])]
    filtered_df.to_csv(filtered_contracts_csv, index=False)
    return fetched_pairs_df, filtered_df

# -------------------------
# Master Runner
# -------------------------

def main():
    print("🔎 Scraping trending tokens from Dexscreener...")
    rearranged_df = scrapeDex()
    if rearranged_df is None or rearranged_df.empty:
        print("❌ No tokens scraped.")
        return

    print("🔎 Getting best pairs from Dexscreener API...")
    rearranged_df_with_contracts = add_contracts_to_df(rearranged_df)
    print(f"✅ Found {len(rearranged_df_with_contracts)} valid tokens")

    print("🔎 Filtering tokens supported by Jupiter...")
    filtered_df, supported_contracts = filter_supported_by_jupiter(rearranged_df_with_contracts)
    print(f"✅ {len(supported_contracts)} tokens supported by Jupiter")

    print("📊 Fetching OHLC data for supported pairs...")
    fetch_and_save_all(
        filtered_df,
        interval="minute",
        pages=20,
        limit=800,
        output_csv="all_pairs_ohlc.csv",
        fetched_pairs_csv="fetched_pairs.csv",
        filtered_contracts_csv="filtered_contracts.csv"
    )
    print("✅ Pipeline completed!")

if __name__ == "__main__":
    main()
