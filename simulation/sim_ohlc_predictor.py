# sim_ohlc_predictor.py
import pandas as pd
import numpy as np
import sqlite3
from typing import Tuple, List

class SimOHLC_Predictor:
    """
    Deterministic, relaxed AI simulator.
    Drop-in replacement for OHLC_Predictor.
    Picks top 2 performing tokens for BUY signals.
    Compatible with ai_orch.py (ignores clf_model/reg_model).
    """

    def __init__(
        self,
        db_path: str,
        clf_model=None,      # ignored, for compatibility
        reg_model=None,      # ignored, for compatibility
        features: List[str] = None,
        prob_threshold: float = 0.5
    ):
        self.db_path = db_path
        self.features = features or []
        self.prob_threshold = prob_threshold

    # -----------------------------
    # Feature prep (kept for realism)
    # -----------------------------
    @staticmethod
    def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
        g = df.sort_values("time").reset_index(drop=True)
        g["return"] = g["close"].pct_change().fillna(0)
        g["rolling_vol"] = g["return"].rolling(5, min_periods=1).std().fillna(0)
        g["rolling_mean"] = g["close"].rolling(5, min_periods=1).mean().fillna(g["close"])
        g["drawdown"] = (g["close"] - g["close"].cummax()) / g["close"].cummax()
        return g

    # -----------------------------
    # Prediction logic for a pair
    # -----------------------------
    def predict_pair(self, pair_id: str, last_close: float, top_pairs: List[str]) -> Tuple[float, int, float, str]:
        """
        Relaxed deterministic logic:
        Only top 2 tokens get BUY signals.
        """
        # Default values
        clf_prob = 0.4
        clf_signal = 0
        reg_pred = 0.0
        decision = "NO_TRADE"

        if pair_id in top_pairs:
            clf_prob = 0.9
            clf_signal = 1
            reg_pred = 0.12
            decision = "BUY"

        return clf_prob, clf_signal, reg_pred, decision

    # -----------------------------
    # Load OHLC from DB
    # -----------------------------
    def load_ohlc_from_db(self) -> pd.DataFrame:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql(
            "SELECT * FROM ohlc_data ORDER BY pair_id, time",
            conn
        )
        conn.close()
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        return df

    # -----------------------------
    # Run predictions for all pairs
    # -----------------------------
    def run_predictions(self) -> pd.DataFrame:
        df = self.load_ohlc_from_db()
        results = []

        if df.empty:
            return pd.DataFrame(results)

        # Compute a simple performance metric (% change over last 6 candles)
        performance = df.groupby("pair_id").apply(
            lambda g: (g["close"].iloc[-1] - g["close"].iloc[-6]) / g["close"].iloc[-6]
            if len(g) >= 6 else 0
        )

        # Pick top 2 performing pairs
        top_pairs = performance.nlargest(2).index.tolist()

        # Generate predictions for all pairs
        for pair_id in df["pair_id"].unique():
            last_close = df[df["pair_id"]==pair_id]["close"].iloc[-1]
            clf_prob, clf_signal, reg_pred, decision = self.predict_pair(pair_id, last_close, top_pairs)

            results.append({
                "pair_id": pair_id,
                "clf_prob": clf_prob,
                "clf_signal": clf_signal,
                "reg_pred": reg_pred,
                "decision": decision
            })

        return pd.DataFrame(results)