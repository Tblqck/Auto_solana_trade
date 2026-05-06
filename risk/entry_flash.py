# flash_lossguard.py
import pandas as pd
from core.db_utils import get_db_connection2
from risk.LossGuard import run_loss_guard

# ------------------------------------------------------------
# Fetch AI-selected tokens
# ------------------------------------------------------------
def fetch_ai_candidates(conn) -> list:
    df = pd.read_sql(
        """
        SELECT DISTINCT pair_id
        FROM ai_thought
        WHERE DECISION = 1
          AND pair_id IS NOT NULL
        """,
        conn
    )
    return df["pair_id"].tolist()


# ------------------------------------------------------------
# Fetch OHLC data for given pair_ids
# ------------------------------------------------------------
def fetch_ohlc(conn, pair_ids) -> dict:
    data = {}
    for pair_id in pair_ids:
        df = pd.read_sql(
            """
            SELECT time, open, high, low, close
            FROM ohlc_data
            WHERE pair_id = ?
            ORDER BY time
            """,
            conn,
            params=(pair_id,)
        )

        if not df.empty:
            df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
            df = df.dropna(subset=["time"])
            data[pair_id] = df

    return data


# ------------------------------------------------------------
# PUBLIC CALLABLE FUNCTION ✅
# ------------------------------------------------------------
def run_flash_lossguard(pair_ids=None):
    """
    Stateless LossGuard scan. Does not write to DB.
    If pair_ids is None, fetch AI-selected tokens automatically.

    Returns:
        dict with keys:
        - safe: list of safe tokens
        - no_data: tokens without OHLC data
    """
    conn = get_db_connection2()
    results = {
        "safe": [],
        "no_data": []
    }

    try:
        if pair_ids is None:
            pair_ids = fetch_ai_candidates(conn)

        if not pair_ids:
            print("⚠️ No AI-selected tokens found.")
            return results

        ohlc_map = fetch_ohlc(conn, pair_ids)

        if not ohlc_map:
            results["no_data"].extend(pair_ids)
            return results

        # Run LossGuard logic (pure calculation)
        safe_pairs = run_loss_guard(ohlc_map, conn=None)  # conn=None to prevent writes

        results["safe"].extend(safe_pairs)
        no_data_pairs = set(pair_ids) - set(safe_pairs)
        results["no_data"].extend(no_data_pairs)

        return results

    finally:
        conn.close()


# ------------------------------------------------------------
# CLI ENTRY
# ------------------------------------------------------------
if __name__ == "__main__":
    output = run_flash_lossguard()
    print("\n===== FLASH LOSSGUARD SUMMARY =====")
    print("SAFE:", output["safe"])
    print("NO DATA:", output["no_data"])
