# stoploss_orchestrator.py

from datetime import datetime, timezone
from db_utils import get_db_connection2

get_db_connection = get_db_connection2

# ----------------------------
# Default baseline risk parameters
# ----------------------------
BASE_HARD_STOP = 0.10        # 10% max loss
BASE_TRAIL_START = 0.10      # Start trailing after 10% profit
BASE_TRAIL_DISTANCE = 0.10   # 10% trailing drawdown


def run_stoploss_orch(contract_list, price_map):
    """
    Stoploss orchestration.

    Args:
        contract_list: List of pair_ids to process
        price_map: dict of pair_id -> current_price

    Returns:
        dict of pair_id -> "SAFE" | "SELL"
    """

    signals = {}
    now = datetime.now(timezone.utc)
    conn = get_db_connection()
    cur = conn.cursor()

    for pair_id in contract_list:
        current_price = price_map.get(pair_id)
        if current_price is None:
            # No price data available
            continue

        # Fetch existing trade risk state
        cur.execute("SELECT * FROM trade_risk_state WHERE pair_id = ?", (pair_id,))
        row = cur.fetchone()
        colnames = [desc[0] for desc in cur.description]

        if row:
            # ----------------------------
            # Existing token: recalc stoploss
            # ----------------------------
            data = dict(zip(colnames, row))
            entry_price = data["entry_price"]
            peak_price = max(data["peak_price"], current_price)

            # Use existing active percentages
            hard_stop_pct = data["hard_stop_pct"]
            trail_start_pct = data["trail_start_pct"]
            trail_distance_pct = data["trail_distance_pct"]
            prev_stop_price = data["stop_price"]

            # Compute profit %
            profit_pct = (current_price - entry_price) / entry_price

            # Hard stop price (from entry)
            hard_stop_price = entry_price * (1 - hard_stop_pct)

            # Trailing logic
            stop_price = max(prev_stop_price, hard_stop_price)
            trigger_type = None
            if profit_pct >= trail_start_pct:
                trailing_stop = peak_price * (1 - trail_distance_pct)
                stop_price = max(stop_price, trailing_stop)
                trigger_type = "TRAILING_STOP"

            # Check if stoploss hit
            decision = "HOLD"
            if current_price <= stop_price:
                decision = "EXIT"
                trigger_type = (
                    "HARD_STOP" if current_price <= hard_stop_price else "TRAILING_STOP"
                )

            # Update DB
            cur.execute("""
                UPDATE trade_risk_state
                SET
                    current_price = ?,
                    peak_price = ?,
                    stop_price = ?,
                    last_decision = ?,
                    trigger_type = ?,
                    last_updated = ?
                WHERE pair_id = ?
            """, (
                current_price,
                peak_price,
                stop_price,
                decision,
                trigger_type,
                now,
                pair_id
            ))

            signals[pair_id] = "SELL" if decision == "EXIT" else "SAFE"

        else:
            # ----------------------------
            # New token: initialize row
            # ----------------------------
            entry_price = current_price
            peak_price = current_price

            base_hard_stop_pct = BASE_HARD_STOP
            base_trail_start_pct = BASE_TRAIL_START
            base_trail_distance_pct = BASE_TRAIL_DISTANCE

            hard_stop_pct = base_hard_stop_pct
            trail_start_pct = base_trail_start_pct
            trail_distance_pct = base_trail_distance_pct

            stop_price = entry_price * (1 - hard_stop_pct)

            last_decision = "SAFE"
            trigger_type = None

            cur.execute("""
                INSERT INTO trade_risk_state (
                    pair_id, entry_price, current_price, peak_price,
                    base_hard_stop_pct, base_trail_start_pct, base_trail_distance_pct,
                    hard_stop_pct, trail_start_pct, trail_distance_pct,
                    stop_price, last_decision, trigger_type, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pair_id, entry_price, current_price, peak_price,
                base_hard_stop_pct, base_trail_start_pct, base_trail_distance_pct,
                hard_stop_pct, trail_start_pct, trail_distance_pct,
                stop_price, last_decision, trigger_type, now
            ))

            signals[pair_id] = "SAFE"

    conn.commit()
    conn.close()
    return signals
