# trade_enricher.py
import pandas as pd
from datetime import datetime, timezone

def enrich_signals(pred_df: pd.DataFrame, current_prices: pd.DataFrame = None) -> pd.DataFrame:
    """
    Convert AI prediction DataFrame into trade-ready table.

    Args:
        pred_df: DataFrame from OHLC_Predictor with columns
                 ['pair_id', 'clf_prob', 'reg_pred', 'decision']
        current_prices: Optional DataFrame with ['pair_id', 'Price'] for latest prices.

    Returns:
        DataFrame ready for saving / downstream consumption.
    """
    if pred_df.empty:
        print("[Enricher] No predictions to process.")
        return pd.DataFrame()

    df = pred_df.copy()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Initialize trade-ready columns
    df["TIME_QUEUED"] = now_iso
    df["TRADE_STAT"] = 0  # PENDING
    df["IN_PRICE"] = None
    df["LAST_PRICE_OLDER"] = None
    df["TIME_INPRICE"] = None
    df["ID"] = range(1, len(df) + 1)

    # DECISION: 1 if BUY, 0 otherwise (robust to whitespace/case)
    df["DECISION"] = df["decision"].apply(lambda x: 1 if str(x).upper().startswith("BUY") else 0)

    # LAST_PRICE: get from current_prices if provided, else leave as None
    if current_prices is not None and not current_prices.empty:
        # --- normalize column names to lowercase ---
        current_prices = current_prices.rename(columns=str.lower)

        # Defensive check
        if "price" not in current_prices.columns:
            raise ValueError(
                f"Expected 'price' column in current_prices, got {current_prices.columns.tolist()}"
            )

        price_map = current_prices.set_index("pair_id")["price"].to_dict()
        df["LAST_PRICE"] = df["pair_id"].map(price_map)
        df["LAST_PRICE_OLDER"] = df["LAST_PRICE"]
    else:
        df["LAST_PRICE"] = None
        df["LAST_PRICE_OLDER"] = None

    # Keep only relevant columns for downstream
    final_cols = [
        "ID", "pair_id", "DECISION", "TIME_QUEUED", "TRADE_STAT",
        "LAST_PRICE", "IN_PRICE", "LAST_PRICE_OLDER", "TIME_INPRICE",
        "clf_prob", "reg_pred"
    ]
    df = df[final_cols]

    return df
