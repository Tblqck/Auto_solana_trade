import requests
import time

# Contract address (token on Solana)
CONTRACT_ADDRESS = "GBAk9Ws6iCpoST3fj6Z7hnyqvJ6FwNFWAnjuXGkxZ2iy"

# Dexscreener trades API endpoint (Solana network)
API_URL = f"https://api.dexscreener.com/latest/dex/trades/solana/{CONTRACT_ADDRESS}"

def fetch_trades():
    try:
        response = requests.get(API_URL, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ API error {response.status_code}")
            return []

        data = response.json()
        trades = data.get("trades", [])
        return trades

    except Exception as e:
        print(f"❌ Error fetching trades: {e}")
        return []

def display_trades(trades):
    if not trades:
        print("No trades found.")
        return

    print("\n=== Latest Trades ===")
    for trade in trades[:10]:  # show last 10 trades
        t_type = trade.get("type", "unknown").upper()  # BUY or SELL
        price = trade.get("priceUsd", "?")
        amount_token = trade.get("amount", "?")
        amount_usd = trade.get("amountUsd", "?")
        trader = trade.get("maker", "N/A")  # trader wallet address

        print(f"{t_type} | {amount_token} tokens (~${amount_usd}) @ ${price} | Trader: {trader}")

if __name__ == "__main__":
    while True:
        trades = fetch_trades()
        display_trades(trades)
        time.sleep(10)  # refresh every 10s
