# stoploss_tightener_core.py


def compute_tightened_stoploss(
    *,
    entry_price: float,
    current_price: float,
    stop_price: float | None = None
) -> float:
    """
    Tighten stop-loss only when in profit. Never loosens stop.
    Does not override hard stop on losing positions — that is the
    stoploss_orchestrator's responsibility.

    Rules:
    - Losing or flat (profit <= 0): return current stop unchanged
    - Small profit (0% < profit <= 5%): protect break-even (stop = entry)
    - Profit > 5%: lock in 5% gain (stop = entry * 1.05)
    - Never lower the stop below its previous value
    """
    profit_pct = (current_price - entry_price) / entry_price

    if profit_pct <= 0:
        # Losing position — let hard stop handle it, tightener does nothing
        new_stop = stop_price if stop_price is not None else entry_price * 0.90
    elif profit_pct <= 0.05:
        # Small profit — protect break-even
        new_stop = entry_price
    else:
        # Meaningful profit — lock in 5%
        new_stop = entry_price * 1.05

    # Never lower the stop
    if stop_price is not None:
        new_stop = max(new_stop, stop_price)

    return new_stop
