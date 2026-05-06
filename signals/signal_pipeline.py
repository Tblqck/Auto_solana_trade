"""
Unified Signal Pipeline — deterministic, single-pass.
"""

from datetime import datetime, timezone
from typing import Dict, List

from ai.aibot import run_ai_bot_cycle
from risk.entry import run_lossguard_cycle
from risk.stoploss_orchestrator import run_stoploss_orch
from risk.stoploss_tightener_orch import run_tightener
from core.db_utils import get_db_connection2, get_db_connection

FALLBACK_MINUTES = 20
FALLBACK_PRICE_TOLERANCE = 0.001  # 0.1%


def fetch_active_trades(conn) -> set:
    """Return pair_ids that are in trade_risk_state AND have an open position in live_trades."""
    cur = conn.cursor()
    cur.execute("""
        SELECT trs.pair_id
        FROM trade_risk_state trs
        INNER JOIN live_trades lt ON lt.pair_id = trs.pair_id
        WHERE lt.status = 'OPEN'
    """)
    return {row[0] for row in cur.fetchall()}


def fetch_latest_prices(conn, pair_ids: List[str]) -> Dict[str, float]:
    prices = {}
    cur = conn.cursor()
    for pair_id in pair_ids:
        cur.execute("""
            SELECT close FROM ohlc_data
            WHERE pair_id = ?
            ORDER BY time DESC LIMIT 1
        """, (pair_id,))
        row = cur.fetchone()
        if row:
            prices[pair_id] = float(row[0])
    return prices


def _check_fallback_sells(price_map: Dict[str, float], now: datetime, existing_sells: list) -> list:
    """Return pair_ids for open positions that have been flat for FALLBACK_MINUTES."""
    extra_sells = []
    try:
        live_conn = get_db_connection()
        cur = live_conn.cursor()
        cur.execute("""
            SELECT pair_id, entry_price, entry_time
            FROM live_trades
            WHERE status = 'OPEN'
        """)
        rows = cur.fetchall()
        live_conn.close()

        for pair_id, entry_price, entry_time in rows:
            if not entry_time or not entry_price:
                continue
            if pair_id in existing_sells:
                continue

            if isinstance(entry_time, str):
                entry_time = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)

            age_min = (now - entry_time).total_seconds() / 60
            if age_min < FALLBACK_MINUTES:
                continue

            current = price_map.get(pair_id)
            if not current or entry_price <= 0:
                continue

            price_change = abs(current - entry_price) / entry_price
            if price_change <= FALLBACK_PRICE_TOLERANCE:
                print(f"[Pipeline] Fallback SELL: {pair_id} flat {age_min:.0f}min delta={price_change*100:.3f}%")
                extra_sells.append(pair_id)

    except Exception as e:
        print(f"[Pipeline] Fallback sell check failed: {e}")

    return extra_sells


def run_signal_pipeline() -> dict:
    now = datetime.now(timezone.utc)
    conn = get_db_connection2()

    try:
        # Step 1 — AI cycle
        run_ai_bot_cycle()

        # Step 2 — Load only actually-owned active trades
        active_trades = fetch_active_trades(conn)

        # Step 3 — Stoploss check on active trades
        sell_signals = []
        price_map: Dict[str, float] = {}

        if active_trades:
            price_map = fetch_latest_prices(conn, list(active_trades))
            sl_check = run_stoploss_orch(list(active_trades), price_map)
            for pair_id, sig in sl_check.items():
                if sig == "SELL":
                    sell_signals.append(pair_id)

        # Step 3b — Fallback SELL for stale flat positions
        fallback_sells = _check_fallback_sells(price_map, now, sell_signals)
        sell_signals.extend(fallback_sells)

        remaining_active = [p for p in active_trades if p not in sell_signals]

        # Step 4 — LossGuard scan for new safe tokens
        lg_result = run_lossguard_cycle()
        new_safe = lg_result.get("safe", [])
        fresh_tokens = [p for p in new_safe if p not in remaining_active]

        if fresh_tokens:
            fresh_prices = fetch_latest_prices(conn, fresh_tokens)
            price_map.update(fresh_prices)
            # Seed trade_risk_state with signal-time entry price for new BUY candidates
            run_stoploss_orch(fresh_tokens, fresh_prices)

        # Step 5 — Tighten stops on held positions that LossGuard also approved
        flipped_candidates = [p for p in remaining_active if p in new_safe]
        tightened = {}
        if flipped_candidates:
            tightened = run_tightener(flipped_candidates)

        return {
            "timestamp": now,
            "new_safe": fresh_tokens,
            "sell": sell_signals,
            "tightened": tightened,
        }

    finally:
        conn.close()


if __name__ == "__main__":
    out = run_signal_pipeline()
    print("\n===== SIGNAL PIPELINE =====")
    print("NEW SAFE:", out["new_safe"])
    print("SELL:    ", out["sell"])
    print("TIGHTENED:", out["tightened"])
