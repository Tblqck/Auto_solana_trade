# stoploss_tightener_core.py

# Profit protection tiers: (profit_threshold, locked_gain_fraction)
# When profit reaches the threshold, the stop floor is raised to entry * (1 + locked_gain).
# Tiers are applied as a ratchet — the stop can only move up, never down.
PROFIT_TIERS = [
    (0.02, 0.00),   # +2%   profit → break-even (protect full capital)
    (0.05, 0.02),   # +5%   profit → lock in 2%
    (0.10, 0.05),   # +10%  profit → lock in 5%
    (0.20, 0.12),   # +20%  profit → lock in 12%
    (0.50, 0.30),   # +50%  profit → lock in 30%
    (1.00, 0.60),   # +100% profit → lock in 60%  (floor = entry × 1.60)
    (1.50, 1.00),   # +150% profit → lock in 100% (floor = entry × 2.00)
    (2.00, 1.40),   # +200% profit → lock in 140% (floor = entry × 2.40)
    (3.00, 2.20),   # +300% profit → lock in 220% (floor = entry × 3.20)
    (5.00, 3.50),   # +500% profit → lock in 350% (floor = entry × 4.50)
]


def compute_tightened_stoploss(
    *,
    entry_price: float,
    current_price: float,
    peak_price: float,
    stop_price: float | None = None,
) -> float:
    """
    Tiered profit-protection ratchet. Pure function, no side effects.

    Walks PROFIT_TIERS from highest to lowest to find the best matching tier
    and floors the stop at the corresponding locked gain above entry.

    Never lowers the stop below its previous value.
    Losing positions are untouched — the stoploss orchestrator's hard stop owns those.
    """
    profit_pct = (current_price - entry_price) / entry_price

    # Default: keep existing stop unchanged
    new_stop = stop_price if stop_price is not None else entry_price * 0.93

    # Find the highest tier the current profit qualifies for
    for threshold, locked_gain in reversed(PROFIT_TIERS):
        if profit_pct >= threshold:
            tier_floor = entry_price * (1.0 + locked_gain)
            new_stop = max(new_stop, tier_floor)
            break

    # Ratchet: never lower the stop below its previous value
    if stop_price is not None:
        new_stop = max(new_stop, stop_price)

    return new_stop
