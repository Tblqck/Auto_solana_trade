# ============================================================
# entry.py
# Scheduler / data orchestrator for LossGuard
# ============================================================

import pandas as pd
from core.db_utils import get_db_connection2
from risk.LossGuard import run_loss_guard

INTERVAL = 3600  # 1 hour


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
# Fetch last scan status per token
# ------------------------------------------------------------
def fetch_last_scan_status(conn) -> dict:
    df = pd.read_sql(
        """
        SELECT pair_id, time_scanned, status
        FROM loss_guard_log
        WHERE (pair_id, time_scanned) IN (
            SELECT pair_id, MAX(time_scanned)
            FROM loss_guard_log
            GROUP BY pair_id
        )
        """,
        conn,
        parse_dates=[]
    )

    if df.empty:
        return {}

    df["time_scanned"] = pd.to_datetime(df["time_scanned"], errors="coerce", utc=True)

    return {
        row["pair_id"]: {
            "time": row["time_scanned"],
            "status": row["status"]
        }
        for _, row in df.iterrows()
    }


# ------------------------------------------------------------
# Fetch OHLC
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
# PUBLIC CALLABLE FUNCTION  ✅
# ------------------------------------------------------------
def run_lossguard_cycle():
    print("[LossGuard] Running scan")

    conn = get_db_connection2()
    now = pd.Timestamp.utcnow()

    results = {
        "safe": [],
        "safe_hold": [],
        "blocked": [],
        "no_data": [],
        "scanned": []
    }

    try:
        candidates = fetch_ai_candidates(conn)
        last_status = fetch_last_scan_status(conn)

        to_scan = []

        for pair_id in candidates:
            last = last_status.get(pair_id)

            if not last:
                to_scan.append(pair_id)
                continue

            seconds_passed = (now - last["time"]).total_seconds()
            status = last["status"]

            if status in ("SAFE", "BLOCKED") and seconds_passed < INTERVAL:
                print(f"[LossGuard] HOLD ({status}, cooldown): {pair_id}")

                if status == "SAFE":
                    results["safe_hold"].append(pair_id)
                else:
                    results["blocked"].append(pair_id)

                continue

            to_scan.append(pair_id)

        if not to_scan:
            print("[LossGuard] No tokens need scanning")
            return results

        ohlc_map = fetch_ohlc(conn, to_scan)

        if not ohlc_map:
            results["no_data"].extend(to_scan)
            return results

        safe_pairs = run_loss_guard(ohlc_map, conn=conn)

        results["safe"].extend(safe_pairs)
        results["scanned"].extend(to_scan)

        print(f"[LossGuard] Safe pairs: {len(safe_pairs)}")

        return results

    finally:
        conn.close()


# ------------------------------------------------------------
# CLI ENTRY (still works)
# ------------------------------------------------------------
if __name__ == "__main__":
    output = run_lossguard_cycle()

    print("\n===== FINAL SUMMARY =====")
    print("SAFE:", len(output["safe"]))
    print("SAFE (HOLD):", len(output["safe_hold"]))
    print("BLOCKED:", len(output["blocked"]))
    print("NO DATA:", len(output["no_data"]))
