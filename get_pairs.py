import os
import time
import datetime
import requests
import pandas as pd
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from seleniumbase import Driver
from db_utils import get_db_connection

# -------------------------
# Utility Functions
# -------------------------

def processDataRaw(data):
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
    df = df.drop(index=0).reset_index(drop=True)
    for idx, row in df.iterrows():
        try:
            col4 = str(row[4]) if 4 in row else ""
            col6 = str(row[6]) if 6 in row else ""
            if col4 != "SOL":
                df.at[idx, 5] = col4
        except Exception as e:
            print(f"Error processing row {idx}: {e}")
    return pd.DataFrame({"Column5": df[5]})

def scrapeDex():
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
                        "pair_id": pair.get("pairAddress"),  # <-- lowercase + underscore
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
        return best_pair
    except Exception as e:
        print(f"Error fetching pairs for {token_name}: {e}")
        return None

def add_contracts_to_db(rearranged_df):
    results = []
    conn = get_db_connection()
    cur = conn.cursor()
    for token in rearranged_df["Column5"]:
        best_pair = get_best_pair(token)
        if best_pair:
            results.append(best_pair)
            # Insert or replace into DB
            cur.execute("""
                INSERT OR REPLACE INTO tokens
                (token, symbol, contract, pair_id, price, marketcap_raw, liquidity_raw, fdv_raw, marketcap, liquidity, fdv)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                best_pair["Token"], best_pair["Symbol"], best_pair["Contract"], best_pair["pair_id"],
                best_pair["Price"], best_pair["MarketCap_raw"], best_pair["Liquidity_raw"], best_pair["FDV_raw"],
                best_pair["MarketCap"], best_pair["Liquidity"], best_pair["FDV"]
            ))
        time.sleep(0.5)
    conn.commit()
    conn.close()
    return results

def filter_supported_by_jupiter_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tokens")
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=[col[0] for col in cur.description])
    conn.close()

    # Same filtering logic as before
    supported = []
    contracts = df["contract"].dropna().unique().tolist()  # lowercase to match DB
    batch_size = 50
    lite_url="https://lite-api.jup.ag/price/v3"
    main_url="https://api.jup.ag/price/v2"

    for i in range(0, len(contracts), batch_size):
        batch = contracts[i:i+batch_size]
        ids = ",".join(batch)
        try:
            resp = requests.get(lite_url, params={"ids": ids}, timeout=6)
            if resp.status_code == 200:
                supported.extend(resp.json().keys())
                continue
        except:
            pass
        try:
            resp = requests.get(main_url, params={"ids": ids}, timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    supported.extend(data.keys())
                elif isinstance(data, list):
                    for d in data:
                        if "id" in d:
                            supported.append(d["id"])
        except:
            pass

    supported_set = set(supported)
    filtered_df = df[df["contract"].isin(supported_set)]

    # Save supported tokens into DB
    conn = get_db_connection()
    cur = conn.cursor()
    for _, row in filtered_df.iterrows():
        cur.execute("""
            INSERT OR REPLACE INTO supported_tokens
            (contract, token, symbol, pair_id, price, marketcap, liquidity, fdv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["contract"], row["token"], row["symbol"], row["pair_id"],  # <-- fixed here
            row["price"], row["marketcap"], row["liquidity"], row["fdv"]
        ))
    conn.commit()
    conn.close()
    return filtered_df

# -------------------------
# Master Runner
# -------------------------

def main():
    print("🔎 Scraping trending tokens from Dexscreener...")
    rearranged_df = scrapeDex()
    if rearranged_df is None or rearranged_df.empty:
        print("❌ No tokens scraped.")
        return

    print("🔎 Adding best pairs to DB...")
    add_contracts_to_db(rearranged_df)

    print("🔎 Filtering tokens supported by Jupiter...")
    filtered_df = filter_supported_by_jupiter_db()
    print(f"✅ {len(filtered_df)} tokens supported by Jupiter")

def run_all():
    """Alias for running the full Dex scraping + DB update pipeline."""
    main()

if __name__ == "__main__":
    run_all()