import requests

def get_price_from_dexscreener(token_address):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()

        # Check if we have pairs
        pairs = data.get("pairs", [])
        if not pairs:
            print(f"❌ No trading pairs found for {token_address}")
            return None

        # Pick the first pair (or best one by liquidity)
        best_pair = max(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0)))

        price = best_pair.get("priceUsd")
        base = best_pair.get("baseToken", {}).get("symbol")
        quote = best_pair.get("quoteToken", {}).get("symbol")

        print(f"✅ {base}/{quote} price: ${price}")
        return price

    except Exception as e:
        print("⚠️ Error fetching price:", e)
        return None

# 🔹 Replace with your token mint / contract
token_address = "LiGHtkg3uTa9836RaNkKLLriqTNRcMdRAhqjGWNv777"
get_price_from_dexscreener(token_address)
