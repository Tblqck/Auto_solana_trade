# sync/archive_ohlc_remote.py
"""
Runs ON the EC2 instance, invoked over SSH by sync/archive_ohlc.py (the
local orchestrator) -- not part of the live trading pipeline, on-demand
only. Exports or deletes ohlc_data rows older than a cutoff timestamp.

  python -m sync.archive_ohlc_remote --mode export --cutoff <iso> --out <path>
  python -m sync.archive_ohlc_remote --mode delete --cutoff <iso>
"""
import argparse
import csv

from core.db_utils import get_db_connection2


def export_old(cutoff: str, out_path: str) -> int:
    conn = get_db_connection2()
    cur = conn.cursor()
    cur.execute(
        "SELECT pair_id, time, open, high, low, close, volume FROM ohlc_data WHERE time < ?",
        (cutoff,),
    )
    rows = cur.fetchall()
    conn.close()

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pair_id", "time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    return len(rows)


def delete_old(cutoff: str) -> int:
    conn = get_db_connection2()
    conn.execute("PRAGMA busy_timeout = 5000")
    cur = conn.cursor()
    cur.execute("DELETE FROM ohlc_data WHERE time < ?", (cutoff,))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", required=True, help="ISO timestamp; rows older than this are affected")
    parser.add_argument("--mode", required=True, choices=["export", "delete"])
    parser.add_argument("--out", default=None, help="CSV output path (export mode)")
    args = parser.parse_args()

    if args.mode == "export":
        if not args.out:
            raise SystemExit("--out required for export mode")
        print(export_old(args.cutoff, args.out))
    else:
        print(delete_old(args.cutoff))
