import requests

TOKEN_CONTRACT = "H74CYmXgMkYHYuSRsZt6RJb4NYp2u72Vw8BS5huApump"

def fetch_jupiter_price(contract):
    url = "https://quote-api.jup.ag/v4/price"
    try:
        resp = requests.get(url, params={"ids": contract}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if contract in data:
            token_data = data[contract]
            price = token_data.get("priceUsd")
            liquidity = token_data.get("liquidity")
            return price, liquidity
        print(f"{contract} not listed on Jupiter")
    except Exception as e:
        print(f"Error fetching {contract}: {e}")
    return None, None

price, liquidity = fetch_jupiter_price(TOKEN_CONTRACT)

if price is not None:
    print(f"Jupiter price for {TOKEN_CONTRACT}: ${price}")
    print(f"Liquidity: {liquidity}")
else:
    print(f"No price data found on Jupiter for {TOKEN_CONTRACT}")