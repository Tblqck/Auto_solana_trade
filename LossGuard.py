# ============================================================
# LossGuard.py
# Pure risk analysis module
# ============================================================

import pandas as pd
import numpy as np

MAX_SINGLE_CANDLE_DROP = 0.12
MAX_DRAWDOWN = 0.20
MIN_CANDLES = 10


# ------------------------------------------------------------
def compute_risk_metrics(df: pd.DataFrame) -> dict:
    df = df.copy()

    df["return"] = df["close"].pct_change().fillna(0)
    df["candle_dump"] = (df["open"] - df["low"]) / df["open"]

    worst_candle = float(df["candle_dump"].max())

    recent_high = df["high"].rolling(10).max().iloc[-1]
    last_price = df["close"].iloc[-1]

    drawdown = (
        (recent_high - last_price) / recent_high
        if recent_high > 0 else 0
    )

    return {
        "worst_candle": worst_candle,
        "drawdown": drawdown
    }


# ------------------------------------------------------------
def loss_guard_pass(metrics: dict) -> bool:
    if metrics["worst_candle"] >= MAX_SINGLE_CANDLE_DROP:
        return False
    if metrics["drawdown"] >= MAX_DRAWDOWN:
        return False
    return True


# ------------------------------------------------------------
def run_loss_guard(pair_ohlc_map: dict, conn=None):
    safe_pairs = []

    for pair_id, ohlc in pair_ohlc_map.items():

        if len(ohlc) < MIN_CANDLES:
            status = "SKIPPED"
            reason = f"insufficient OHLC ({len(ohlc)})"
            print(f"⏭️ SKIPPED (data): {pair_id}")

        else:
            metrics = compute_risk_metrics(ohlc)

            if loss_guard_pass(metrics):
                status = "SAFE"
                reason = ""
                safe_pairs.append(pair_id)
                print(f"✅ SAFE: {pair_id}")
            else:
                status = "BLOCKED"
                reason = "risk thresholds breached"
                print(f"❌ BLOCKED: {pair_id}")

        if conn:
            conn.execute(
                """
                INSERT INTO loss_guard_log
                (pair_id, time_scanned, status, reason)
                VALUES (?, ?, ?, ?)
                """,
                (
                    pair_id,
                    pd.Timestamp.utcnow().isoformat(),
                    status,
                    reason
                )
            )
            conn.commit()

    return safe_pairs
