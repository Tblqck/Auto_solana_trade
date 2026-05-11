# stoploss_orchestrator.py

from datetime import datetime, timezone
from core.db_utils import get_db_connection2
from risk.stoploss_core import compute_stoploss

get_db_connection = get_db_connection2

BASE_HARD_STOP = 0.07
BASE_TRAIL_START = 0.10
BASE_TRAIL_DISTANCE = 0.07


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
            continue

        cur.execute("SELECT * FROM trade_risk_state WHERE pair_id = ?", (pair_id,))
        row = cur.fetchone()
        colnames = [desc[0] for desc in cur.description]

        if row:
            data = dict(zip(colnames, row))

            result = compute_stoploss(
                entry_price=data["entry_price"],
                current_price=current_price,
                peak_price=data["peak_price"],
                stop_price=data["stop_price"],
                hard_stop_pct=data["hard_stop_pct"],
                trail_start_pct=data["trail_start_pct"],
                trail_distance_pct=data["trail_distance_pct"],
            )

            cur.execute("""
                UPDATE trade_risk_state
                SET
                    current_price = ?,
                    peak_price    = ?,
                    stop_price    = ?,
                    last_decision = ?,
                    trigger_type  = ?,
                    last_updated  = ?
                WHERE pair_id = ?
            """, (
                current_price,
                result["peak_price"],
                result["stop_price"],
                result["decision"],
                result["trigger_type"],
                now,
                pair_id
            ))

            decision = result["decision"]
            reason   = result.get("trigger_type") or "SAFE"
            signals[pair_id] = {"decision": decision, "reason": reason}

        else:
            # New token — seed trade_risk_state with signal-time entry price
            stop_price = current_price * (1 - BASE_HARD_STOP)

            cur.execute("""
                INSERT INTO trade_risk_state (
                    pair_id, entry_price, current_price, peak_price,
                    base_hard_stop_pct, base_trail_start_pct, base_trail_distance_pct,
                    hard_stop_pct, trail_start_pct, trail_distance_pct,
                    stop_price, last_decision, trigger_type, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pair_id, current_price, current_price, current_price,
                BASE_HARD_STOP, BASE_TRAIL_START, BASE_TRAIL_DISTANCE,
                BASE_HARD_STOP, BASE_TRAIL_START, BASE_TRAIL_DISTANCE,
                stop_price, "SAFE", None, now
            ))

            signals[pair_id] = {"decision": "SAFE", "reason": "SAFE"}

    conn.commit()
    conn.close()
    return signals
