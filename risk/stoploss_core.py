# stoploss_core.py
from typing import Dict, Optional

# At high profit, trail tightens to give back less of the run before exit.
# Applied in order (highest threshold first) — first match wins.
TRAIL_DISTANCE_TIERS = [
    (2.00, 0.05),  # +200%+ profit → trail 5% below peak
    (1.00, 0.06),  # +100%+ profit → trail 6% below peak
]
# Below +100% the base trail_distance_pct (0.07) from the orchestrator applies.


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
        # Tighten trail distance at high profit levels to preserve more of the run
        effective_trail = trail_distance_pct
        for min_profit, tighter_dist in TRAIL_DISTANCE_TIERS:
            if profit_pct >= min_profit:
                effective_trail = tighter_dist
                break
        trailing_stop = peak_price * (1 - effective_trail)
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
