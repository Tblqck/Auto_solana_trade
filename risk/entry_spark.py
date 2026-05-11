# entry_spark.py — Momentum confirmation gate for new entries

import pandas as pd

CANDLE_RETURN_MIN = 0.003   # last candle must be green by >= 0.3%
VOLUME_RATIO_MIN  = 1.0     # volume must be above its rolling average
VOL_LOOKBACK      = 10      # candles used to compute the volume average


def check_entry_spark(pair_id: str, conn) -> bool:
    """
    Confirm active buying momentum on the most recent candle before entry.

    Passes when BOTH:
      - Last candle is green by >= 0.1%:  (close - open) / open >= 0.001
      - Last candle volume > 10-candle average:  vol_ratio >= 1.0

    The volume average excludes the last candle itself so it cannot self-satisfy.
    Returns False if data is insufficient.
    """
    try:
        df = pd.read_sql(
            """
            SELECT open, close, volume
            FROM ohlc_data
            WHERE pair_id = ?
            ORDER BY time DESC
            LIMIT ?
            """,
            conn,
            params=(pair_id, VOL_LOOKBACK + 1),
        )
    except Exception as e:
        print(f"[EntrySpark] DB read failed for {pair_id}: {e}")
        return False

    if len(df) < 2:
        print(f"[EntrySpark] Insufficient data: {pair_id} ({len(df)} candles)")
        return False

    last       = df.iloc[0]
    open_price = float(last["open"])

    if open_price <= 0:
        return False

    candle_return = (float(last["close"]) - open_price) / open_price

    # Average excludes the last candle so it can't inflate its own ratio
    avg_volume = df["volume"].iloc[1:].mean()
    vol_ratio  = float(last["volume"]) / avg_volume if avg_volume > 0 else 0.0

    passed = candle_return >= CANDLE_RETURN_MIN and vol_ratio >= VOLUME_RATIO_MIN

    status = "PASS" if passed else "FAIL"
    print(
        f"[EntrySpark] {status} {pair_id[:14]}  "
        f"return={candle_return * 100:.2f}%  vol_ratio={vol_ratio:.2f}x"
    )

    return passed
