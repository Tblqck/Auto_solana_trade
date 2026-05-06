import os
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
COINGECKO_KEY = os.getenv("PRIVATE_KEY")  # optional, not required for free endpoints

# -------------------------------
# Token / Coin setup
# -------------------------------
coin_id = "nexusmind"  # replace with actual CoinGecko ID for your contract
vs_currency = "usd"
interval = "30m"

# CoinGecko OHLC endpoint only allows certain intervals:
# 1, 5, 15, 30, 60, 90, 180, 1d, 7d, 14d, 30d, 90d, 365d
# Docs: https://www.coingecko.com/en/api/documentation

# -------------------------------
# Calculate timestamps
# -------------------------------
now = datetime.utcnow()
since = now - timedelta(hours=24)  # last 24 hours

# CoinGecko OHLC endpoint expects number of days as integer
# We'll fetch 1 day data
days = 1

# -------------------------------
# Fetch OHLC from CoinGecko
# -------------------------------
url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
params = {
    "vs_currency": vs_currency,
    "days": days,
}

resp = requests.get(url, params=params)
data = resp.json()

# -------------------------------
# Convert to DataFrame
# -------------------------------
# data format: [ [timestamp, open, high, low, close], ...]
df = pd.DataFrame(data, columns=["time", "open", "high", "low", "close"])
df["time"] = pd.to_datetime(df["time"], unit="ms")  # convert to datetime
df = df.set_index("time")

# Filter 30-min interval candles only
df_30m = df[df.index.minute % 30 == 0]

print(df_30m)