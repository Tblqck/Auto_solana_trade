# data/watchlist_prune.py
"""
Daily prune of stale/illiquid tokens from the active watchlist
(supported_tokens). Never touches a token with an OPEN position in
live_trades. Only deletes from supported_tokens -- tokens and ohlc_data
history are left alone, since that history stays valuable for model
retraining even after a token drops off the active watchlist.

"Stale" = it HAD OHLC data but nothing fresh in STALE_HOURS (Data_Loop_core
stopped finding data for it -- delisted, drained, or dead). A token with NO
data yet is left alone -- that just means DataLoop hasn't reached it in its
rotation yet, not that it's stale.
"Illiquid" = current liquidity_raw has decayed below MIN_LIQUIDITY_USD
since it was discovered.
"""
from datetime import datetime, timezone, timedelta

from core.db_utils import get_db_connection2

STALE_HOURS        = 48
MIN_LIQUIDITY_USD  = 30_000


def find_prune_candidates(conn) -> list[str]:
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT pair_id FROM live_trades WHERE status = 'OPEN'")
    held_pairs = {row[0] for row in cur.fetchall()}

    # supported_tokens only stores a human-formatted liquidity string
    # ("$100K") -- join tokens for the numeric liquidity_raw.
    cur.execute("""
        SELECT st.contract, st.pair_id, t.liquidity_raw
        FROM supported_tokens st
        LEFT JOIN tokens t ON t.contract = st.contract
    """)
    all_supported = cur.fetchall()

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=STALE_HOURS)).isoformat()

    to_prune = []
    for contract, pair_id, liquidity_raw in all_supported:
        if pair_id in held_pairs:
            continue  # never prune an actively-held position

        cur.execute("SELECT MAX(time) FROM ohlc_data WHERE pair_id = ?", (pair_id,))
        last_candle = cur.fetchone()[0]
        # No data yet just means DataLoop hasn't reached it in its rotation
        # yet (freshly discovered) -- that's not staleness, leave it alone.
        is_stale = (last_candle is not None) and (str(last_candle) < cutoff)

        try:
            is_illiquid = liquidity_raw is not None and float(liquidity_raw) < MIN_LIQUIDITY_USD
        except (TypeError, ValueError):
            is_illiquid = False

        if is_stale or is_illiquid:
            to_prune.append(contract)

    return to_prune


def prune_watchlist() -> dict:
    conn = get_db_connection2()
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        candidates = find_prune_candidates(conn)
        if not candidates:
            print("[Prune] Nothing to prune.")
            return {"pruned": 0}

        cur = conn.cursor()
        cur.executemany(
            "DELETE FROM supported_tokens WHERE contract = ?",
            [(c,) for c in candidates],
        )
        conn.commit()
        print(f"[Prune] Removed {len(candidates)} stale/illiquid token(s) from the active watchlist")
        return {"pruned": len(candidates), "contracts": candidates}
    finally:
        conn.close()


if __name__ == "__main__":
    prune_watchlist()
