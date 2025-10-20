# allocation_manager.py
import pandas as pd
import os
from datetime import datetime, timezone, timedelta

ALLOCATION = "allocation_tracker.csv"
SIM_PORTFOLIO = "sim_portfolio.csv"
SIM_TOKEN_LOG = "sim_token_log.csv"
CONTRACTS_FILE = "filtered_contracts.csv"

def get_allocation(hours=12):
    """
    Get constant allocation USD for buys.
    Reuse allocation if stop_timestamp > now, else recalc.
    """
    now = datetime.now(timezone.utc)

    # --- Step 1: Check existing allocation ---
    if os.path.exists(ALLOCATION):
        df = pd.read_csv(ALLOCATION)
        if not df.empty:
            stop_ts = datetime.fromisoformat(df.iloc[0]["stop_timestamp"])
            alloc_usd = float(df.iloc[0]["allocation_usd"])
            if now <= stop_ts:
                print(f"[ALLOCATION] Reusing ${alloc_usd:.2f} until {stop_ts}")
                return alloc_usd

    # --- Step 2: Recalculate allocation ---
    # Get latest total value
    if not os.path.exists(SIM_PORTFOLIO) or os.path.getsize(SIM_PORTFOLIO) == 0:
        raise RuntimeError("Portfolio file missing or empty, cannot calculate allocation.")
    port_df = pd.read_csv(SIM_PORTFOLIO)
    total_usd = float(port_df.iloc[-1]["TOTAL_VALUE_USD"])

    # Get SOL USD value from latest token log
    if not os.path.exists(SIM_TOKEN_LOG) or os.path.getsize(SIM_TOKEN_LOG) == 0:
        sol_usd_value = 0
    else:
        token_df = pd.read_csv(SIM_TOKEN_LOG)
        sol_rows = token_df[token_df["Contract"] == "SOL"]
        if sol_rows.empty:
            sol_usd_value = 0
        else:
            latest = sol_rows.iloc[-1]
            sol_usd_value = float(latest["USD_Value"])

    allocatable_usd = max(0, total_usd - sol_usd_value)

    # Count how many contracts in filtered_contracts.csv
    if not os.path.exists(CONTRACTS_FILE) or os.path.getsize(CONTRACTS_FILE) == 0:
        raise RuntimeError("Contracts file missing or empty, cannot divide allocation.")
    contracts_df = pd.read_csv(CONTRACTS_FILE, dtype=str)
    n_contracts = len(contracts_df)
    if n_contracts == 0:
        raise RuntimeError("No contracts found in filtered_contracts.csv.")

    allocation_usd = allocatable_usd / n_contracts

    # --- Step 3: Save allocation ---
    stop_ts = now + timedelta(hours=hours)
    pd.DataFrame([{
        "stop_timestamp": stop_ts.isoformat(),
        "allocation_usd": allocation_usd
    }]).to_csv(ALLOCATION, index=False)

    print(f"[ALLOCATION] New allocation ${allocation_usd:.2f} valid until {stop_ts}")
    return allocation_usd
