import requests

USE_SIMULATION = False   # flip OFF for real API fetch

# Simulation configuration
SIM_BASE_PRICE = 0.001  # base price for simulation
SIM_PERCENT = -0.5    # +20% (use negative for -20%)

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

    # --- Real API fetch ---
    url = f"https://api.dexscreener.com/latest/dex/pairs/{chain}/" + ",".join(pair_ids)
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
        print(f"❌ Error fetching DexScreener prices: {e}")
        return {}
