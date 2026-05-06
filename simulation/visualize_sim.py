# visualize_sim.py
import pandas as pd
import matplotlib.pyplot as plt

# --- Load simulation token log ---
df = pd.read_csv("sim_token_log.csv")

# Convert timestamp to datetime
df["Timestamp"] = pd.to_datetime(df["Timestamp"])

# --- Compute total portfolio value per timestamp ---
portfolio = df.groupby("Timestamp")["USD_Value"].sum().reset_index()
portfolio.rename(columns={"USD_Value": "TOTAL_VALUE_USD"}, inplace=True)

# --- Plot portfolio total value ---
plt.figure(figsize=(12, 6))
plt.plot(portfolio["Timestamp"], portfolio["TOTAL_VALUE_USD"], marker="o", label="Portfolio Value (USD)")
plt.title("Total Portfolio Value Over Time")
plt.xlabel("Time")
plt.ylabel("USD Value")
plt.xticks(rotation=45)
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# --- Plot per-token USD values ---
plt.figure(figsize=(12, 6))
for contract, subdf in df.groupby("Contract"):
    plt.plot(subdf["Timestamp"], subdf["USD_Value"], marker="o", label=contract)

plt.title("Per-Token USD Value Over Time")
plt.xlabel("Time")
plt.ylabel("USD Value")
plt.xticks(rotation=45)
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()

# --- Plot per-token Amounts (holdings) ---
plt.figure(figsize=(12, 6))
for contract, subdf in df.groupby("Contract"):
    plt.plot(subdf["Timestamp"], subdf["Amount"], marker="o", label=f"{contract} Amount")

plt.title("Token Holdings Over Time")
plt.xlabel("Time")
plt.ylabel("Amount Held")
plt.xticks(rotation=45)
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
