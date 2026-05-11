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

FALLBACK_MINUTES = 50
FALLBACK_PRICE_TOLERANCE = 0.001  # 0.1%

LIQUIDITY_CHECK_INTERVAL_MINUTES = 10
MIN_LIQUIDITY_RATIO = 0.40  # sell if current liquidity < 40% of entry


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


def _check_liquidity_sells(now: datetime, existing_sells: list) -> list:
    """
    Return pair_ids whose liquidity has dropped below MIN_LIQUIDITY_RATIO of entry.
    Runs at most once per LIQUIDITY_CHECK_INTERVAL_MINUTES per position.
    """
    extra_sells = []
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT pair_id, contract, entry_liquidity, last_liquidity_check
            FROM live_trades
            WHERE status = 'OPEN' AND entry_liquidity > 0
        """)
        rows = cur.fetchall()

        for pair_id, contract, entry_liq, last_check in rows:
            if pair_id in existing_sells:
                continue

            # Throttle: only check every LIQUIDITY_CHECK_INTERVAL_MINUTES
            if last_check:
                try:
                    lc_dt = datetime.fromisoformat(last_check.replace("Z", "+00:00"))
                    if lc_dt.tzinfo is None:
                        lc_dt = lc_dt.replace(tzinfo=timezone.utc)
                    if (now - lc_dt).total_seconds() / 60 < LIQUIDITY_CHECK_INTERVAL_MINUTES:
                        continue
                except Exception:
                    pass

            # Fetch current liquidity — prefer tokens.liquidity_raw, fall back to ai_thought
            current_liq = None
            cur.execute("SELECT liquidity_raw FROM tokens WHERE contract=?", (contract,))
            liq_row = cur.fetchone()
            if liq_row and liq_row[0] is not None:
                current_liq = float(liq_row[0])
            else:
                cur.execute("""
                    SELECT liquidity FROM ai_thought
                    WHERE pair_id=? ORDER BY time_queued DESC LIMIT 1
                """, (pair_id,))
                ait = cur.fetchone()
                if ait and ait[0]:
                    try:
                        current_liq = float(str(ait[0]).replace("$", "").replace(",", ""))
                    except Exception:
                        pass

            # Stamp the check time regardless of outcome
            cur.execute(
                "UPDATE live_trades SET last_liquidity_check=? WHERE pair_id=?",
                (now.isoformat(), pair_id),
            )

            if current_liq is None:
                continue

            ratio = current_liq / entry_liq if entry_liq > 0 else 1.0
            if ratio < MIN_LIQUIDITY_RATIO:
                print(
                    f"[Pipeline] Liquidity SELL: {pair_id} "
                    f"liq=${current_liq:,.0f} ({ratio*100:.0f}% of entry ${entry_liq:,.0f})"
                )
                extra_sells.append(pair_id)

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Pipeline] Liquidity check failed: {e}")
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

        sell_reasons: Dict[str, str] = {}

        if active_trades:
            price_map = fetch_latest_prices(conn, list(active_trades))
            sl_check = run_stoploss_orch(list(active_trades), price_map)
            for pair_id, result in sl_check.items():
                if result["decision"] == "SELL":
                    sell_signals.append(pair_id)
                    sell_reasons[pair_id] = result["reason"]

        # Step 3b — Fallback SELL for stale flat positions (50 min, 0.1% tolerance)
        fallback_sells = _check_fallback_sells(price_map, now, sell_signals)
        for pair_id in fallback_sells:
            sell_reasons[pair_id] = "FALLBACK_FLAT"
        sell_signals.extend(fallback_sells)

        # Step 3c — Liquidity watch (every 10 min per position, sell if < 40% of entry)
        liq_sells = _check_liquidity_sells(now, sell_signals)
        sell_signals.extend(liq_sells)

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

        # Step 5 — Tighten stops on ALL held positions regardless of LossGuard result.
        # Profit protection must not be gated on whether LossGuard approved new buys.
        tightened = {}
        if remaining_active:
            tightened = run_tightener(list(remaining_active))

        return {
            "timestamp": now,
            "new_safe": fresh_tokens,
            "sell": sell_signals,
            "sell_reasons": sell_reasons,
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
