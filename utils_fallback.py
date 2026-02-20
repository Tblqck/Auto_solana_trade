# utils_fallback.py
import pandas as pd
from datetime import datetime, timedelta, timezone

FALLBACK_MINUTES = 20
PRICE_TOLERANCE = 0.001  # 0.1% tolerance

def check_fallback(buybook_file, live_prices, active_contracts, active_positions, pair_map):
    signals = []
    try:
        df = pd.read_csv(buybook_file)
        if df.empty:
            return signals, active_contracts, active_positions, pair_map

        # only check active contracts
        df = df[df["contract"].isin(active_contracts)]
        if df.empty:
            return signals, active_contracts, active_positions, pair_map

        # Keep only the most recent buy per contract
        latest = df.sort_values("time_queued").groupby("contract").tail(1)

        for _, row in latest.iterrows():
            cid = row["contract"]
            buy_price = float(row["price"])
            queued_time = datetime.fromisoformat(str(row["time_queued"]).replace("Z", "+00:00"))

            if cid not in live_prices:
                continue

            current_price = float(live_prices[cid])
            age = datetime.now(timezone.utc) - queued_time

            price_change = abs(current_price - buy_price) / buy_price

            if age >= timedelta(minutes=FALLBACK_MINUTES) and price_change <= PRICE_TOLERANCE:
                signals.append({
                    "contract": cid,
                    "decision": "SELL",
                    "reason": f"Fallback horizon hit (age {age}, Δ={price_change*100:.3f}%)",
                    "time": datetime.now(timezone.utc).isoformat()
                })
                if cid in active_contracts:
                    active_contracts.remove(cid)
                if cid in active_positions:
                    del active_positions[cid]
                if cid in pair_map:
                    del pair_map[cid]

    except FileNotFoundError:
        print("⚠️ buybook.csv not found")

    return signals, active_contracts, active_positions, pair_map
