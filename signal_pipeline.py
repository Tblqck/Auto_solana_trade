# signal.py
"""
Unified Signal Pipeline
Callable, deterministic, stateless
"""

from datetime import datetime, timezone
from typing import Dict, List

from aibot import run_ai_bot_cycle
from entry import run_lossguard_cycle
from stoploss_orchestrator import run_stoploss_orch
from stoploss_tightener_orch import run_tightener
from db_utils import get_db_connection2


# -------------------------is --- -------------------------
# Helpers
# --------------------------------------------------
def fetch_active_trades(conn) -> set:
    """
    Tokens already being traded (have stoploss state in DB).
    """
    cur = conn.cursor()
    cur.execute("SELECT pair_id FROM trade_risk_state")
    return {row[0] for row in cur.fetchall()}


def fetch_latest_prices(conn, pair_ids: List[str]) -> Dict[str, float]:
    """
    Fetch the latest close price for each token.
    """
    prices = {}
    cur = conn.cursor()
    for pair_id in pair_ids:
        cur.execute("""
            SELECT close
            FROM ohlc_data
            WHERE pair_id = ?
            ORDER BY time DESC
            LIMIT 1
        """, (pair_id,))
        row = cur.fetchone()
        if row:
            prices[pair_id] = float(row[0])
    return prices


# --------------------------------------------------
# PUBLIC ENTRY POINT ✅
# --------------------------------------------------
def run_signal_pipeline() -> dict:
    """
    Run one full signal iteration:
      1. Run AI -> update ai_thought
      2. Check existing trades for SELL
      3. Run LossGuard -> determine new safe tokens
      4. Run Stoploss orchestrator -> initialize/update stoploss for new tokens
      5. Tighten stoploss for flipped active trades
    """
    now = datetime.now(timezone.utc)
    conn = get_db_connection2()

    try:
        # ==========================
        # 1️⃣ Run AI cycle
        # ==========================
        run_ai_bot_cycle()

        # ==========================
        # 2️⃣ Load current active trades
        # ==========================
        active_trades = fetch_active_trades(conn)

        # ==========================
        # 3️⃣ Check existing trades for SELL
        # ==========================
        sell_signals = []
        if active_trades:
            # Fetch latest prices
            price_map = fetch_latest_prices(conn, list(active_trades))
            # Check stoploss / broken rules
            sl_check = run_stoploss_orch(list(active_trades), price_map)
            for pair_id, sig in sl_check.items():
                if sig == "SELL":
                    sell_signals.append(pair_id)

        # Filter out sold tokens from active trades
        remaining_active = [p for p in active_trades if p not in sell_signals]

        # ==========================
        # 4️⃣ Run LossGuard cycle for new tokens
        # ==========================
        lg_result = run_lossguard_cycle()
        new_safe = lg_result.get("safe", [])
        fresh_tokens = [p for p in new_safe if p not in remaining_active]

        safe_signals = []
        if fresh_tokens:
            price_map = fetch_latest_prices(conn, fresh_tokens)
            sl_signals = run_stoploss_orch(fresh_tokens, price_map)
            for pair_id, sig in sl_signals.items():
                if sig == "SELL":
                    sell_signals.append(pair_id)
                else:
                    safe_signals.append(pair_id)

        # ==========================
        # 5️⃣ Existing active trades: detect flipped tokens for tightening
        # ==========================
        flipped_candidates = [
            p for p in remaining_active
            if p in new_safe  # AI or LossGuard says SAFE
        ]
        tightened = {}
        if flipped_candidates:
            tightened = run_tightener(flipped_candidates)

        return {
            "timestamp": now,
            "new_safe": fresh_tokens,
            "sell": sell_signals,
            "tightened": tightened
        }

    finally:
        conn.close()



# --------------------------------------------------
# CLI test
# --------------------------------------------------
if __name__ == "__main__":
    out = run_signal_pipeline()
    print("\n===== SIGNAL PIPELINE =====")
    print("NEW SAFE:", out["new_safe"])
    print("SELL:", out["sell"])
    print("TIGHTENED:", out["tightened"])
