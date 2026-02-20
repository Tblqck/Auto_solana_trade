# stoploss_core.py
from typing import Dict, Optional


def compute_stoploss(
    *,
    entry_price: float,
    current_price: float,
    peak_price: float,
    stop_price: float,
    hard_stop_pct: float,
    trail_start_pct: float,
    trail_distance_pct: float,
) -> Dict:
    """
    PURE stoploss engine.
    No DB. No side effects. Deterministic.

    Returns:
    {
        stop_price: float,
        peak_price: float,
        decision: "SAFE" | "SELL",
        trigger_type: None | "HARD_STOP" | "TRAILING_STOP"
    }
    """

    # 1️⃣ Update peak
    peak_price = max(peak_price, current_price)

    # 2️⃣ Compute hard stop from entry
    hard_stop_price = entry_price * (1 - hard_stop_pct)

    # 3️⃣ Base stop cannot go below hard stop
    new_stop = max(stop_price, hard_stop_price)

    # 4️⃣ Activate trailing only after enough profit
    profit_pct = (current_price - entry_price) / entry_price
    if profit_pct >= trail_start_pct:
        trailing_stop = peak_price * (1 - trail_distance_pct)
        new_stop = max(new_stop, trailing_stop)

    # 5️⃣ Decide
    decision = "SAFE"
    trigger_type = None

    if current_price <= new_stop:
        decision = "SELL"
        trigger_type = (
            "HARD_STOP"
            if current_price <= hard_stop_price
            else "TRAILING_STOP"
        )

    return {
        "stop_price": new_stop,
        "peak_price": peak_price,
        "decision": decision,
        "trigger_type": trigger_type
    }
