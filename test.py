import pandas as pd

# ---- Parameters ----
CSV_FILE = r"C:\Users\kate\Documents\sol-trade\archive\20250912_114737\all_pairs_ohlc.csv"

# configs: (core stoploss, trailing stop)
configs = [
    ("7% core + 3% trail", 0.07, 0.03),
    ("5% core + 3% trail", 0.05, 0.03),
    ("5% core + 4% trail", 0.05, 0.04),
    ("7% core + 4% trail", 0.07, 0.04),
]

# ---- Load ----
df = pd.read_csv(CSV_FILE)
df.columns = [c.strip().lower() for c in df.columns]
df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)

aggregate_results = []

# ---- Simple regime detector ----
def detect_regime(sub, lookback=20):
    """Return 'calm' or 'storm' based on rolling volatility."""
    sub = sub.sort_values("time").reset_index(drop=True)
    sub["return"] = sub["close"].pct_change()
    vol = sub["return"].rolling(lookback).std().mean()

    # thresholds can be tuned depending on your dataset
    if vol < 0.02:   # <2% std dev → calm
        return "calm"
    else:
        return "storm"

for name, core_sl, trail_sl in configs:
    results = []
    calm_count, storm_count = 0, 0

    for pair, sub in df.groupby("pair_id"):
        regime = detect_regime(sub)

        if regime == "calm":
            calm_count += 1
        else:
            storm_count += 1

        sub = sub.sort_values("time").reset_index(drop=True)

        balance = 0.0
        trades = 0
        stoploss_hits = 0
        trail_hits = 0
        entry_price = None
        highest_price = None

        for _, row in sub.iterrows():
            price_open = row["open"]
            price_high = row["high"]
            price_low = row["low"]
            price_close = row["close"]

            if entry_price is None:
                entry_price = price_open
                highest_price = price_open
                continue

            # update high water mark
            highest_price = max(highest_price, price_high)

            # core stoploss
            if price_low <= entry_price * (1 - core_sl):
                pnl = -core_sl
                balance += pnl
                trades += 1
                stoploss_hits += 1
                entry_price = None
                highest_price = None
                continue

            # trailing stop
            if price_low <= highest_price * (1 - trail_sl):
                pnl = (highest_price * (1 - trail_sl) - entry_price) / entry_price
                balance += pnl
                trades += 1
                trail_hits += 1
                entry_price = None
                highest_price = None
                continue

            # otherwise close at end of bar
            pnl = (price_close - entry_price) / entry_price
            balance += pnl
            trades += 1
            entry_price = None
            highest_price = None

        results.append(balance * 100)  # percent return for pair

    # aggregate portfolio view
    total_pnl = sum(results)
    avg_pnl = total_pnl / len(results) if results else 0
    aggregate_results.append({
        "config": name,
        "pairs_tested": len(results),
        "calm_pairs": calm_count,
        "storm_pairs": storm_count,
        "total_pnl_%": total_pnl,
        "avg_pnl_per_pair_%": avg_pnl
    })

# ---- Save + Show ----
agg_df = pd.DataFrame(aggregate_results)
agg_df.to_csv("aggregate_stoploss_comparison.csv", index=False)
print(agg_df)
