# allocation_manager.py
import os
import pandas as pd
from datetime import datetime, timezone, timedelta
from wallet_state import get_wallet_state  # Your existing wallet_state.py

ALLOCATION_CSV = "allocation_tracker.csv"
NUM_SLOTS = 5  # Max trades per day
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DEFAULT_SLOT_HOURS = 24  # Slot expiration time


def get_dynamic_allocation(hours: int = DEFAULT_SLOT_HOURS):
    """
    Compute dynamic per-slot allocation based on wallet state and open trades.
    Tracks allocations in CSV with slot_id, start_timestamp, and stop_timestamp.
    Automatically expires slots older than `hours`.
    """
    now = datetime.now(timezone.utc)

    # --- Step 1: Read wallet state ---
    wallet = get_wallet_state()  # dict
    usdc_balance = next(
        (t["amount"] for t in wallet.get("tokens", []) if t["mint"] == USDC_MINT),
        0.0
    )
    print(f"[DEBUG] USDC balance: {usdc_balance}")

    # --- Step 2: Read existing allocations CSV ---
    if os.path.exists(ALLOCATION_CSV) and os.path.getsize(ALLOCATION_CSV) > 0:
        df = pd.read_csv(ALLOCATION_CSV)
        # Ensure datetime objects with timezone awareness
        df["start_timestamp"] = pd.to_datetime(df.get("start_timestamp"), utc=True, errors="coerce")
        df["stop_timestamp"] = pd.to_datetime(df.get("stop_timestamp"), utc=True, errors="coerce")
        # Drop invalid rows
        df = df.dropna(subset=["start_timestamp", "stop_timestamp"])
        # Keep only active allocations
        df = df[df["stop_timestamp"] > now]
        committed_usdc = df["allocation_usd"].sum() if not df.empty else 0.0
    else:
        df = pd.DataFrame(columns=["slot_id", "start_timestamp", "stop_timestamp", "allocation_usd"])
        committed_usdc = 0.0

    print(f"[DEBUG] Committed USDC from active slots: {committed_usdc}")

    # --- Step 3: Compute remaining USDC and slots ---
    available_usdc = max(0, usdc_balance - committed_usdc)
    remaining_slots = max(0, NUM_SLOTS - len(df))

    if remaining_slots == 0 or available_usdc == 0:
        print("[ALLOCATION] No allocation available (all slots used or zero USDC).")
        return 0.0

    allocation_per_slot = available_usdc / remaining_slots

    # --- Step 4: Assign new slot_id ---
    next_slot_id = 1 if df.empty else df["slot_id"].max() + 1

    stop_ts = now + timedelta(hours=hours)
    new_row = pd.DataFrame([{
        "slot_id": next_slot_id,
        "start_timestamp": now.isoformat(),
        "stop_timestamp": stop_ts.isoformat(),
        "allocation_usd": allocation_per_slot
    }])

    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(ALLOCATION_CSV, index=False)

    print(f"[ALLOCATION] Slot {next_slot_id} allocated ${allocation_per_slot:.2f} "
          f"(expires {stop_ts.isoformat()}) for {remaining_slots} remaining slots")
    return allocation_per_slot


# ----------------------------
# CLI Test
# ----------------------------
if __name__ == "__main__":
    alloc = get_dynamic_allocation()
    print(f"Dynamic allocation per trade: ${alloc:.2f}")