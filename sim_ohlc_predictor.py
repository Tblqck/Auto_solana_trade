import pandas as pd
import numpy as np
import sqlite3
from typing import Tuple


class SimOHLC_Predictor:
    """
    Deterministic, rule-based AI simulator.
    Drop-in replacement for OHLC_Predictor.
    """

    def __init__(
        self,
        db_path: str,
        features: list = None,
        prob_threshold: float = 0.5
    ):
        self.db_path = db_path
        self.features = features or []
        self.prob_threshold = prob_threshold

    # -------------------------------------------------
    # Shared feature prep (kept for realism)
    # -------------------------------------------------
    @staticmethod
    def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
        g = df.sort_values("time").reset_index(drop=True)
        g["return"] = g["close"].pct_change().fillna(0)
        g["rolling_vol"] = g["return"].rolling(5, min_periods=1).std().fillna(0)
        g["rolling_mean"] = g["close"].rolling(5, min_periods=1).mean().fillna(g["close"])
        g["drawdown"] = (g["close"] - g["close"].cummax()) / g["close"].cummax()
        return g

    # -------------------------------------------------
    # SIM DECISION LOGIC (THIS IS THE TRUTH ENGINE)
    # -------------------------------------------------
    def predict_pair(self, group: pd.DataFrame) -> Tuple[float, int, float, str]:
        g = self.prepare_features(group)

        last = g.iloc[-1]

        ret_6 = (g["close"].iloc[-1] - g["close"].iloc[-6]) / g["close"].iloc[-6] if len(g) >= 6 else 0
        ret_2 = (g["close"].iloc[-1] - g["close"].iloc[-3]) / g["close"].iloc[-3] if len(g) >= 3 else 0
        drawdown = last["drawdown"]
        vol = last["rolling_vol"]

        # ----------------------------
        # DETERMINISTIC FLIP RULES
        # ----------------------------

        # 🔴 Panic flip (should trigger tighten, not immediate sell)
        if drawdown < -0.05 and ret_2 < -0.03:
            clf_prob = 0.95
            decision = "NO_TRADE"   # AI flip OFF
            clf_signal = 0
            reg_pred = -0.08

        # 🟠 Fake recovery (tightener zone)
        elif ret_2 > 0.015 and vol > 0.04:
            clf_prob = 0.55
            decision = "NO_TRADE"
            clf_signal = 0
            reg_pred = 0.01

        # 🟢 Strong momentum
        elif ret_6 > 0.06 and drawdown > -0.02:
            clf_prob = 0.9
            decision = "BUY"
            clf_signal = 1
            reg_pred = 0.12

        # ⚪ Chop
        else:
            clf_prob = 0.4
            decision = "NO_TRADE"
            clf_signal = 0
            reg_pred = 0.0

        return clf_prob, clf_signal, reg_pred, decision

    # -------------------------------------------------
    # DB LOAD (UNCHANGED)
    # -------------------------------------------------
    def load_ohlc_from_db(self) -> pd.DataFrame:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql(
            "SELECT * FROM ohlc_data ORDER BY pair_id, time",
            conn
        )
        conn.close()
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        return df

    # -------------------------------------------------
    # OUTPUT FORMAT IDENTICAL TO REAL AI
    # -------------------------------------------------
    def run_predictions(self) -> pd.DataFrame:
        df = self.load_ohlc_from_db()
        results = []

        for pair_id in df["pair_id"].unique():
            group = df[df["pair_id"] == pair_id]
            clf_prob, clf_signal, reg_pred, decision = self.predict_pair(group)

            results.append({
                "pair_id": pair_id,
                "clf_prob": clf_prob,
                "clf_signal": clf_signal,
                "reg_pred": reg_pred,
                "decision": decision
            })

        return pd.DataFrame(results)
