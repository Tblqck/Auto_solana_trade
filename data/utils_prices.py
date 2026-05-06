import requests
import time

USE_SIMULATION = False   # flip OFF for real API fetch

# Simulation configuration
SIM_BASE_PRICE = 0.001  # base price for simulation
SIM_PERCENT = -0.5    # +20% (use negative for -20%)

_DEXSCREENER_BATCH_SIZE = 30  # API hard limit per request
_RETRY_COUNT = 3
_RETRY_WAIT = 5


def _fetch_batch(pair_ids, chain, retries):
    url = f"https://api.dexscreener.com/latest/dex/pairs/{chain}/" + ",".join(pair_ids)
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            prices = {}
            if "pairs" in data:
                for pair in data["pairs"]:
                    pid = pair.get("pairAddress")
                    prices[pid] = float(pair.get("priceUsd", 0))
            return prices
        except Exception as e:
            print(f"⚠️ DexScreener fetch error (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(_RETRY_WAIT)
    return {}


def get_prices_from_dexscreener(pair_ids, chain="solana", percent=None):
    """
    Fetches prices for given pair_ids.
    If USE_SIMULATION=True, returns simulated prices.

    percent: float, e.g., 0.20 for +20%, -0.20 for -20%
    """
    if percent is None:
        percent = SIM_PERCENT

    if USE_SIMULATION:
        prices = {}
        for pid in pair_ids:
            simulated = SIM_BASE_PRICE * (1 + percent)
            prices[pid] = round(simulated, 8)
        print(f"🧪 Simulated prices: {prices}")
        return prices

    # Batch into chunks of 30 (DexScreener API limit)
    prices = {}
    for i in range(0, len(pair_ids), _DEXSCREENER_BATCH_SIZE):
        batch = pair_ids[i:i + _DEXSCREENER_BATCH_SIZE]
        prices.update(_fetch_batch(batch, chain, _RETRY_COUNT))
    return prices
