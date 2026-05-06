# ai_orch.py
import gc
import yaml
import pandas as pd

from ai.ohlc_predictor import OHLC_Predictor
from ai.trade_enricher import enrich_signals
from ai.ai_signal_updater import update_ai_signals
from core.db_utils import get_db_connection

# ---------------------------------------------------
# Predictor singleton — models loaded once per process
# ---------------------------------------------------
_predictor: OHLC_Predictor | None = None


def _get_predictor() -> OHLC_Predictor | None:
    global _predictor
    if _predictor is not None:
        return _predictor
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        _predictor = OHLC_Predictor(
            db_path=config["DB_PATH"],
            clf_model=config["classifier_model"],
            reg_model=config["regressor_model"],
            features=config["features"],
            prob_threshold=config["prob_threshold"]
        )
        print("[AI] Models loaded")
        return _predictor
    except Exception as e:
        print(f"[AI] Model load failed: {e}")
        return None


# ---------------------------------------------------
# Single AI cycle
# ---------------------------------------------------
def run_ai_cycle() -> str:
    signals_df = None
    prices_df = None
    trade_ready_df = None

    try:
        predictor = _get_predictor()
        if predictor is None:
            return "done"

        # Run predictions on ALL tokens — BUY and NO_TRADE
        signals_df = predictor.run_predictions()

        if signals_df is None or signals_df.empty:
            print("[AI] No signals generated")
            return "done"

        if "decision" not in signals_df.columns:
            print("[AI] Missing decision column")
            return "done"

        buy_count = (signals_df["decision"] == "BUY").sum()
        print(f"[AI] Predictions: {len(signals_df)} tokens, {buy_count} BUY signals")

        # Fetch latest price for ALL tokens — needed to track and onboard
        try:
            conn = get_db_connection()
            prices_df = pd.read_sql(
                """
                SELECT t1.pair_id, t1.close AS price
                FROM ohlc_data t1
                INNER JOIN (
                    SELECT pair_id, MAX(time) AS max_time
                    FROM ohlc_data
                    GROUP BY pair_id
                ) t2
                ON t1.pair_id = t2.pair_id AND t1.time = t2.max_time
                """,
                conn
            )
            conn.close()
        except Exception as e:
            print(f"[AI] Price fetch failed: {e}")
            return "done"

        # Enrich ALL signals — onboards new BUYs, maintains existing tokens
        trade_ready_df = enrich_signals(signals_df, current_prices=prices_df)
        del signals_df, prices_df
        signals_df = prices_df = None

        if trade_ready_df.empty:
            print("[AI] No enriched signals")
            return "done"

        try:
            update_ai_signals(trade_ready_df)
            print("[AI] Cycle complete")
        except Exception as e:
            print(f"[AI] DB update failed: {e}")

        return "done"

    except Exception as e:
        print(f"[AI] Cycle crashed: {e}")
        return "done"

    finally:
        del signals_df, prices_df, trade_ready_df
        gc.collect()
