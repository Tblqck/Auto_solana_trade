# data/get_pairs.py
"""
Discovers new tradable Solana tokens.

Replaces the old Selenium/DexScreener-scrape approach (its deps —
selenium/seleniumbase — aren't even installed anymore) with GeckoTerminal's
trending-pools API: same provider Data_Loop_core already uses for OHLC, so
the pool address format matches pair_id exactly, no translation needed.

Writes are metadata-only (tokens, supported_tokens via INSERT OR REPLACE) —
never touches trade_risk_state/live_trades, so it can't disturb open
positions or a currently-running signal/trade cycle. Safe to call repeatedly;
already-known contracts are just re-upserted, not duplicated.
"""
import time

import requests

from core.db_utils import get_db_connection

MIN_FDV_USD        = 140_000
MIN_LIQUIDITY_USD  = 100_000
PAGES_PER_RUN       = 3   # ~20 pools/page
GECKO_TRENDING_URL  = "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools"
JUPITER_PRICE_URL   = "https://lite-api.jup.ag/price/v3"


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
    return f"${num:.0f}"


def fetch_trending_pools(pages: int = PAGES_PER_RUN, retries: int = 3, retry_wait: int = 10) -> list[dict]:
    pools = []
    for page in range(1, pages + 1):
        for attempt in range(retries):
            try:
                resp = requests.get(GECKO_TRENDING_URL, params={"page": page}, timeout=15)
                if resp.status_code == 429:
                    print(f"[GetPairs] Rate limited on page {page}, retrying in {retry_wait}s")
                    time.sleep(retry_wait)
                    continue
                if resp.status_code != 200:
                    print(f"[GetPairs] Trending page {page}: HTTP {resp.status_code}")
                    return pools
                data = resp.json().get("data", [])
                if not data:
                    return pools
                pools.extend(data)
                break
            except Exception as e:
                print(f"[GetPairs] Trending fetch failed (page {page}): {e}")
                time.sleep(retry_wait)
        time.sleep(0.5)
    return pools


def filter_candidates(pools: list[dict]) -> list[dict]:
    candidates = []
    for pool in pools:
        try:
            attrs = pool["attributes"]
            fdv = float(attrs.get("fdv_usd") or 0)
            liquidity = float(attrs.get("reserve_in_usd") or 0)
            if fdv < MIN_FDV_USD or liquidity < MIN_LIQUIDITY_USD:
                continue

            base_token_id = pool["relationships"]["base_token"]["data"]["id"]
            contract = base_token_id.split("_", 1)[1] if "_" in base_token_id else base_token_id
            pair_id = attrs.get("address") or pool["id"].split("_", 1)[-1]
            name = attrs.get("name", "")
            symbol = name.split("/")[0].strip() if "/" in name else name

            candidates.append({
                "Token": name,
                "Symbol": symbol,
                "Contract": contract,
                "pair_id": pair_id,
                "Price": f"${float(attrs.get('base_token_price_usd') or 0):.8f}",
                "MarketCap_raw": fdv,
                "Liquidity_raw": liquidity,
                "FDV_raw": fdv,
                "MarketCap": human_format(fdv),
                "Liquidity": human_format(liquidity),
                "FDV": human_format(fdv),
            })
        except Exception as e:
            print(f"[GetPairs] Skipping malformed pool entry: {e}")
    return candidates


def add_contracts_to_db(candidates: list[dict]) -> int:
    if not candidates:
        return 0
    conn = get_db_connection()
    conn.execute("PRAGMA busy_timeout = 5000")
    cur = conn.cursor()
    for c in candidates:
        cur.execute("""
            INSERT OR REPLACE INTO tokens
            (token, symbol, contract, pair_id, price, marketcap_raw, liquidity_raw, fdv_raw, marketcap, liquidity, fdv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c["Token"], c["Symbol"], c["Contract"], c["pair_id"], c["Price"],
            c["MarketCap_raw"], c["Liquidity_raw"], c["FDV_raw"],
            c["MarketCap"], c["Liquidity"], c["FDV"],
        ))
    conn.commit()
    conn.close()
    return len(candidates)


def filter_supported_by_jupiter_db() -> int:
    """Cross-check every known `tokens` row against Jupiter's price API;
    upsert the tradable subset into supported_tokens."""
    conn = get_db_connection()
    conn.execute("PRAGMA busy_timeout = 5000")
    cur = conn.cursor()
    cur.execute("SELECT * FROM tokens")
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description]

    contracts = list({row[cols.index("contract")] for row in rows if row[cols.index("contract")]})
    supported_set = set()
    batch_size = 50

    for i in range(0, len(contracts), batch_size):
        batch = contracts[i:i + batch_size]
        for attempt in range(3):
            try:
                resp = requests.get(JUPITER_PRICE_URL, params={"ids": ",".join(batch)}, timeout=8)
                if resp.status_code == 429:
                    time.sleep(5)
                    continue
                if resp.status_code == 200:
                    supported_set.update(resp.json().keys())
                break
            except Exception as e:
                print(f"[GetPairs] Jupiter check failed (batch {i}): {e}")
                break
        time.sleep(0.2)

    inserted = 0
    for row in rows:
        row_d = dict(zip(cols, row))
        if row_d["contract"] not in supported_set:
            continue
        cur.execute("""
            INSERT OR REPLACE INTO supported_tokens
            (contract, token, symbol, pair_id, price, marketcap, liquidity, fdv)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row_d["contract"], row_d["token"], row_d["symbol"], row_d["pair_id"],
            row_d["price"], row_d["marketcap"], row_d["liquidity"], row_d["fdv"],
        ))
        inserted += 1
    conn.commit()
    conn.close()
    return inserted


def run_all() -> dict:
    """Full discovery pass: fetch trending pools -> quality filter ->
    upsert tokens -> cross-check Jupiter tradability -> upsert supported_tokens."""
    print("[GetPairs] Fetching trending pools from GeckoTerminal...")
    pools = fetch_trending_pools()
    print(f"[GetPairs] {len(pools)} pools fetched")

    candidates = filter_candidates(pools)
    print(f"[GetPairs] {len(candidates)} pass quality filters "
          f"(fdv>=${MIN_FDV_USD:,}, liq>=${MIN_LIQUIDITY_USD:,})")

    add_contracts_to_db(candidates)
    supported = filter_supported_by_jupiter_db()
    print(f"[GetPairs] {supported} tokens confirmed tradable on Jupiter")

    return {"candidates": len(candidates), "supported": supported}


if __name__ == "__main__":
    run_all()
