import pandas as pd
import numpy as np
import joblib
import sqlite3
from typing import Tuple


class OHLC_Predictor:
    def __init__(self, db_path: str, clf_model: str, reg_model: str, features: list, prob_threshold: float):
        self.db_path = db_path
        self.clf = joblib.load(clf_model)
        self.reg = joblib.load(reg_model)
        self.features = features
        self.prob_threshold = prob_threshold

    @staticmethod
    def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
        g = df.sort_values("time").reset_index(drop=True)
        eps = 1e-10

        g["return"]    = g["close"].pct_change().fillna(0)
        g["return_3"]  = g["close"].pct_change(3).fillna(0)
        g["return_10"] = g["close"].pct_change(10).fillna(0)

        g["rolling_vol"]  = g["return"].rolling(5, min_periods=1).std().fillna(0)
        g["rolling_mean"] = g["close"].rolling(5, min_periods=1).mean().fillna(g["close"])

        vol_ma = g["volume"].rolling(10, min_periods=1).mean().replace(0, eps)
        g["volume_ratio"] = (g["volume"] / vol_ma).fillna(1.0)

        candle_range = (g["high"] - g["low"]).replace(0, eps)
        g["body_ratio"] = (g["close"] - g["open"]).abs() / candle_range
        g["body_ratio"] = g["body_ratio"].fillna(0).clip(0, 1)

        g["close_vs_mean"] = (g["close"] - g["rolling_mean"]) / (g["rolling_mean"] + eps)
        g["close_vs_mean"] = g["close_vs_mean"].fillna(0)

        return g

    def predict_pair(self, group: pd.DataFrame) -> Tuple[float, int, float, str]:
        g = self.prepare_features(group)
        X = g[self.features].astype(float).fillna(0)

        try:
            probs = self.clf.predict_proba(X)[:, 1]
        except Exception:
            probs = self.clf.predict(X)

        clf_prob = float(probs[-1]) if len(probs) else np.nan
        clf_signal = int(clf_prob >= self.prob_threshold) if not np.isnan(clf_prob) else 0

        try:
            reg_preds = self.reg.predict(X)
        except Exception:
            reg_preds = np.zeros(len(X))

        reg_pred = float(reg_preds[-1]) if len(reg_preds) else np.nan
        decision = "BUY" if clf_signal == 1 else "NO_TRADE"

        return clf_prob, clf_signal, reg_pred, decision

    def load_ohlc_from_db(self) -> pd.DataFrame:
        """Load full OHLC history for all pairs."""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql(
            "SELECT * FROM ohlc_data ORDER BY pair_id, time",
            conn,
            parse_dates=False
        )
        conn.close()
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
        return df

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
        del df  # free full OHLC table from memory immediately after predictions
        return pd.DataFrame(results)
