# stoploss_tightener_orch.py
from datetime import datetime, timezone
from core.db_utils import get_db_connection2
from risk.stoploss_tightener_core import compute_tightened_stoploss

get_db_connection = get_db_connection2


def run_tightener(pair_ids: list[str]) -> dict[str, float]:
    """
    Orchestrator for tightening stop-losses.

    Args:
        pair_ids: List of token pair_ids to tighten
    Returns:
        Dict of pair_id -> new stop_price
    """
    updated_stops = {}
    now = datetime.now(timezone.utc)

    conn = get_db_connection()
    cur = conn.cursor()

    for pair_id in pair_ids:
        # Fetch current trade info
        cur.execute(
            """
            SELECT entry_price, current_price, stop_price
            FROM trade_risk_state
            WHERE pair_id = ?
            """,
            (pair_id,)
        )
        row = cur.fetchone()
        if not row:
            continue

        entry_price, current_price, stop_price = row

        # Compute tightened stop-loss
        new_stop = compute_tightened_stoploss(
            entry_price=entry_price,
            current_price=current_price,
            stop_price=stop_price
        )

        # Update DB only if stop moved UP (never loosen risk)
        if new_stop > stop_price:
            cur.execute(
                """
                UPDATE trade_risk_state
                SET stop_price = ?, last_updated = ?
                WHERE pair_id = ?
                """,
                (new_stop, now, pair_id)
            )

        updated_stops[pair_id] = new_stop

    conn.commit()
    conn.close()

    return updated_stops
