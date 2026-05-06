#!/usr/bin/env python3
"""
models/train_models.py

Trains and saves both ML models used by the sol_trade signal pipeline:

  models/model_classifier.pkl  —  LightGBM classifier  → clf_prob  (P(BUY))
  models/model_regressor.pkl   —  LightGBM regressor   → reg_pred  (forward return)

Feature set (must stay in sync with config.yaml and ohlc_predictor.prepare_features):
  Raw OHLC  :  open, high, low, close, volume
  Returns   :  return (1-bar), return_3 (3-bar), return_10 (10-bar)
  Rolling   :  rolling_vol, rolling_mean, volume_ratio
  Candle    :  body_ratio, close_vs_mean

Label construction:
  BUY (1)  : forward return over FORWARD_CANDLES >= BUY_THRESHOLD
             AND worst single-candle drop in that window < MAX_SINGLE_DROP
             (eliminates pumps that immediately dump — common on meme coins)
  reg_pred : max forward return over the same window (captures upside potential)

Data sources (tried in order):
  1. --db   : ohlc_data table from a SQLite DB  (default: db_files/dex_pipeline.db)
  2. --csv  : CSV with columns pair_id, time, open, high, low, close, volume
  3. Both   : --db + --csv flags together; rows are merged and deduplicated

Usage:
  python models/train_models.py
  python models/train_models.py --db db_files/dex_pipeline_local_mod.db
  python models/train_models.py --csv lmao_ohlc.csv
  python models/train_models.py --db db_files/dex_pipeline.db --csv extra_ohlc.csv
"""

import argparse
import os
import sqlite3
import sys
import warnings

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.metrics import (
    classification_report,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
)

warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Config — tune these to match your trading strategy
# ---------------------------------------------------------------------------

FORWARD_CANDLES   = 10     # how many 1-min candles ahead to measure the outcome
BUY_THRESHOLD     = 0.02   # +2 % forward return required to label as BUY
MAX_SINGLE_DROP   = 0.06   # reject BUY label if any candle in the window drops >6 %
TRAIN_RATIO       = 0.75   # first 75 % of time-ordered rows go to training
MIN_ROWS_PER_PAIR = 30     # pairs with fewer candles are dropped before training
MIN_TOTAL_ROWS    = 500    # abort if we end up with fewer labelled rows than this

MODEL_DIR    = os.path.join(os.path.dirname(__file__))
CLF_PATH     = os.path.join(MODEL_DIR, "model_classifier.pkl")
REG_PATH     = os.path.join(MODEL_DIR, "model_regressor.pkl")
DEFAULT_DB   = os.path.join("db_files", "dex_pipeline.db")

FEATURES = [
    # raw OHLC
    "open", "high", "low", "close", "volume",
    # 1-bar, 3-bar, 10-bar returns — short/medium momentum
    "return", "return_3", "return_10",
    # rolling stats
    "rolling_vol",    # 5-bar return std  — local volatility
    "rolling_mean",   # 5-bar close mean  — trend anchor
    "volume_ratio",   # volume / 10-bar mean volume — spike detector
    # candle shape features
    "body_ratio",     # |close-open| / candle range — conviction
    "close_vs_mean",  # (close - rolling_mean) / rolling_mean — mean-reversion signal
]

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_from_db(db_path: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        print(f"[train] DB not found: {db_path}")
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql(
            "SELECT pair_id, time, open, high, low, close, volume FROM ohlc_data ORDER BY pair_id, time",
            conn,
        )
    except Exception as e:
        print(f"[train] Could not read ohlc_data from {db_path}: {e}")
        df = pd.DataFrame()
    conn.close()
    print(f"[train] Loaded {len(df):,} rows from DB: {db_path}")
    return df


def load_from_csv(csv_path: str) -> pd.DataFrame:
    if not os.path.exists(csv_path):
        print(f"[train] CSV not found: {csv_path}")
        return pd.DataFrame()
    df = pd.read_csv(csv_path)
    required = {"pair_id", "time", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        print(f"[train] CSV missing columns: {missing}")
        return pd.DataFrame()
    print(f"[train] Loaded {len(df):,} rows from CSV: {csv_path}")
    return df[list(required)]


def merge_sources(*dfs) -> pd.DataFrame:
    non_empty = [d for d in dfs if not d.empty]
    if not non_empty:
        return pd.DataFrame()
    combined = pd.concat(non_empty, ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset=["pair_id", "time"])
    after = len(combined)
    if before != after:
        print(f"[train] Deduplicated {before - after:,} duplicate rows")
    return combined

# ---------------------------------------------------------------------------
# Feature engineering  (must mirror ohlc_predictor.prepare_features)
# ---------------------------------------------------------------------------

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all features for one pair's candle sequence.
    Input df must be sorted by time and contain open/high/low/close/volume.
    """
    g = df.copy().sort_values("time").reset_index(drop=True)

    eps = 1e-10

    # returns
    g["return"]    = g["close"].pct_change().fillna(0)
    g["return_3"]  = g["close"].pct_change(3).fillna(0)
    g["return_10"] = g["close"].pct_change(10).fillna(0)

    # rolling stats (5-bar window — matches existing predictor)
    g["rolling_vol"]  = g["return"].rolling(5, min_periods=1).std().fillna(0)
    g["rolling_mean"] = g["close"].rolling(5, min_periods=1).mean().fillna(g["close"])

    # volume spike: current bar vs 10-bar rolling average
    vol_ma = g["volume"].rolling(10, min_periods=1).mean().replace(0, eps)
    g["volume_ratio"] = (g["volume"] / vol_ma).fillna(1.0)

    # candle body ratio: how much of the range is body (0 = pure doji, 1 = no wicks)
    candle_range = (g["high"] - g["low"]).replace(0, eps)
    g["body_ratio"] = (g["close"] - g["open"]).abs() / candle_range
    g["body_ratio"] = g["body_ratio"].fillna(0).clip(0, 1)

    # price position vs rolling mean (mean-reversion / trend signal)
    g["close_vs_mean"] = (g["close"] - g["rolling_mean"]) / (g["rolling_mean"] + eps)
    g["close_vs_mean"] = g["close_vs_mean"].fillna(0)

    return g

# ---------------------------------------------------------------------------
# Label construction
# ---------------------------------------------------------------------------

def build_labels(df: pd.DataFrame, fwd: int, threshold: float, max_drop: float) -> pd.DataFrame:
    """
    Adds two columns to df (which must be sorted by time, single pair):
      label_clf  — 1 if BUY conditions met, 0 otherwise
      label_reg  — max forward return over [t+1, t+fwd] window
    Rows where the forward window is incomplete are dropped.
    """
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    opens  = df["open"].values
    n      = len(closes)

    clf_labels = np.full(n, np.nan)
    reg_labels = np.full(n, np.nan)

    for i in range(n - fwd):
        c0 = closes[i]
        if c0 <= 0:
            continue

        window_closes = closes[i + 1 : i + fwd + 1]
        window_opens  = opens[i + 1 : i + fwd + 1]
        window_lows   = lows[i + 1 : i + fwd + 1]

        # forward return at the end of the window
        fwd_return = (closes[i + fwd] - c0) / c0

        # max return achievable within the window (captures pump potential)
        max_return = (window_closes.max() - c0) / c0 if len(window_closes) else 0.0

        # worst single-candle intra-bar dump: (open - low) / open
        # this filters out pairs that spike then immediately rug
        worst_dump = np.max(
            np.where(window_opens > 0, (window_opens - window_lows) / window_opens, 0)
        )

        # BUY: price goes up by threshold AND no candle rips the floor out
        is_buy = int(fwd_return >= threshold and worst_dump < max_drop)

        clf_labels[i] = is_buy
        reg_labels[i] = max_return

    df = df.copy()
    df["label_clf"] = clf_labels
    df["label_reg"] = reg_labels

    # drop rows where forward window is incomplete
    df = df.dropna(subset=["label_clf", "label_reg"])
    return df

# ---------------------------------------------------------------------------
# Main training pipeline
# ---------------------------------------------------------------------------

def build_dataset(raw_df: pd.DataFrame) -> pd.DataFrame:
    raw_df["time"] = pd.to_datetime(raw_df["time"], utc=True, errors="coerce")
    raw_df = raw_df.dropna(subset=["time", "open", "high", "low", "close"])
    raw_df = raw_df.sort_values(["pair_id", "time"])

    all_rows = []
    pairs = raw_df["pair_id"].unique()
    print(f"[train] Processing {len(pairs):,} pairs...")

    for pair_id in pairs:
        group = raw_df[raw_df["pair_id"] == pair_id].copy()
        if len(group) < MIN_ROWS_PER_PAIR:
            continue

        group = engineer_features(group)
        group = build_labels(group, FORWARD_CANDLES, BUY_THRESHOLD, MAX_SINGLE_DROP)
        all_rows.append(group)

    if not all_rows:
        return pd.DataFrame()

    return pd.concat(all_rows, ignore_index=True)


def time_split(df: pd.DataFrame):
    """Chronological train/test split — no shuffling, respects time order."""
    df = df.sort_values("time").reset_index(drop=True)
    cut = int(len(df) * TRAIN_RATIO)
    return df.iloc[:cut], df.iloc[cut:]


def train(raw_df: pd.DataFrame):
    print("\n[train] Building feature/label dataset...")
    dataset = build_dataset(raw_df)

    if dataset.empty or len(dataset) < MIN_TOTAL_ROWS:
        print(
            f"[train] Not enough labelled rows ({len(dataset)})."
            f" Need at least {MIN_TOTAL_ROWS}."
            f" Collect more OHLC history before retraining."
        )
        sys.exit(1)

    print(f"[train] Dataset: {len(dataset):,} rows")

    train_df, test_df = time_split(dataset)
    print(f"[train] Train: {len(train_df):,} rows  |  Test: {len(test_df):,} rows")

    X_train = train_df[FEATURES].astype(float).fillna(0)
    X_test  = test_df[FEATURES].astype(float).fillna(0)
    y_clf_train = train_df["label_clf"].astype(int)
    y_clf_test  = test_df["label_clf"].astype(int)
    y_reg_train = train_df["label_reg"].astype(float)
    y_reg_test  = test_df["label_reg"].astype(float)

    buy_pct = y_clf_train.mean() * 100
    print(f"[train] BUY rate in training set: {buy_pct:.1f}%")

    # -------------------------------------------------------------------
    # Classifier — LightGBM with imbalance handling
    # -------------------------------------------------------------------
    print("\n[train] Training classifier...")

    clf = LGBMClassifier(
        n_estimators     = 600,
        learning_rate    = 0.05,
        max_depth        = 6,
        num_leaves       = 48,
        min_child_samples= 20,      # avoid fitting to rare patterns
        subsample        = 0.8,
        colsample_bytree = 0.8,
        reg_alpha        = 0.1,     # L1 regularisation
        reg_lambda       = 0.2,     # L2 regularisation
        is_unbalance     = True,    # handles low BUY rate automatically
        random_state     = 42,
        n_jobs           = -1,
        verbose          = -1,
    )
    clf.fit(X_train, y_clf_train)

    y_pred_clf  = clf.predict(X_test)
    y_prob_clf  = clf.predict_proba(X_test)[:, 1]
    auc         = roc_auc_score(y_clf_test, y_prob_clf)
    print(f"[train] Classifier AUC: {auc:.4f}")
    print(classification_report(y_clf_test, y_pred_clf, target_names=["NO_TRADE", "BUY"]))

    # -------------------------------------------------------------------
    # Regressor — LightGBM
    # -------------------------------------------------------------------
    print("[train] Training regressor...")

    reg = LGBMRegressor(
        n_estimators     = 600,
        learning_rate    = 0.05,
        max_depth        = 6,
        num_leaves       = 48,
        min_child_samples= 20,
        subsample        = 0.8,
        colsample_bytree = 0.8,
        reg_alpha        = 0.1,
        reg_lambda       = 0.2,
        random_state     = 42,
        n_jobs           = -1,
        verbose          = -1,
    )
    reg.fit(X_train, y_reg_train)

    y_pred_reg = reg.predict(X_test)
    mae        = mean_absolute_error(y_reg_test, y_pred_reg)
    r2         = r2_score(y_reg_test, y_pred_reg)
    print(f"[train] Regressor  MAE: {mae:.6f}  |  R²: {r2:.4f}")

    # -------------------------------------------------------------------
    # Feature importance summary
    # -------------------------------------------------------------------
    print("\n[train] Top feature importances (classifier):")
    importances = pd.Series(clf.feature_importances_, index=FEATURES).sort_values(ascending=False)
    for feat, imp in importances.items():
        print(f"  {feat:<20} {imp:.0f}")

    # -------------------------------------------------------------------
    # Save models
    # -------------------------------------------------------------------
    joblib.dump(clf, CLF_PATH)
    joblib.dump(reg, REG_PATH)
    print(f"\n[train] Saved  {CLF_PATH}")
    print(f"[train] Saved  {REG_PATH}")
    print("[train] Done.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Train sol_trade ML models")
    parser.add_argument("--db",  default=DEFAULT_DB, help="SQLite DB path")
    parser.add_argument("--csv", default=None,       help="Optional CSV path (merged with DB data)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    db_df  = load_from_db(args.db)
    csv_df = load_from_csv(args.csv) if args.csv else pd.DataFrame()

    raw = merge_sources(db_df, csv_df)

    if raw.empty:
        print("[train] No data loaded. Provide a DB with ohlc_data or pass --csv.")
        sys.exit(1)

    train(raw)
