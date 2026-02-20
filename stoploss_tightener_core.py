# stoploss_tightener_core.py
from typing import Dict


def compute_tightened_stoploss(
    *,
    entry_price: float,
    current_price: float,
    stop_price: float | None = None
) -> float:
    """
    Calculate a tightened stop-loss without loosening it.

    Rules:
    1️⃣ If token is in initial loss/profit (<=5% profit or up to 10% loss),
       set stop-loss at entry - 5% (for loss) or entry + 5% (for small profit)
    2️⃣ If token profit > 5%, set stop-loss at 5% profit (entry*1.05)
    3️⃣ Never reduce the stop-loss below its previous value
    """
    # 1️⃣ Initial levels
    loss_limit_pct = 0.05  # 5% loss allowed
    small_profit_pct = 0.05  # 5% profit to protect

    # 2️⃣ Calculate base stop
    profit_pct = (current_price - entry_price) / entry_price

    if profit_pct <= 0:  # Losing token
        new_stop = entry_price * (1 - loss_limit_pct)
    elif 0 < profit_pct <= small_profit_pct:  # Small profit zone
        new_stop = entry_price  # Protect break-even
    else:  # Profit > small_profit_pct
        new_stop = entry_price * (1 + small_profit_pct)  # Protect 5% profit

    # 3️⃣ Never lower stop-loss
    if stop_price is not None:
        new_stop = max(new_stop, stop_price)

    return new_stop
