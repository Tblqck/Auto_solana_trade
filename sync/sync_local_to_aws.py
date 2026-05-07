import sys
import sqlite3
import time
import pandas as pd
import yaml
from pathlib import Path

_SYNC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SYNC_DIR))

from bridge_aws import RemoteSQLiteBridge

_PROJECT_ROOT = _SYNC_DIR.parent

TABLES_TO_SYNC = [
    {"name": "supported_tokens", "pk": ["contract"],        "bulk": False},
    {"name": "tokens",           "pk": ["contract"],        "bulk": False},
    {"name": "ohlc_data",        "pk": ["pair_id", "time"], "bulk": True},
]


def _get_local_db():
    cfg_path = _PROJECT_ROOT / "config.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return str(_PROJECT_ROOT / cfg["DB_PATH"])


def _get_local_df(table, local_db):
    conn = sqlite3.connect(local_db)
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    conn.close()
    return df


def sync_all():
    local_db = _get_local_db()
    bridge = RemoteSQLiteBridge()
    bridge.connect()

    for tbl in TABLES_TO_SYNC:
        name = tbl["name"]
        pk = tbl["pk"]
        print(f"\nSyncing table: {name}")

        df = _get_local_df(name, local_db)
        if df.empty:
            print(f"Local {name} is empty - skipping")
            continue

        if tbl["bulk"]:
            bridge.bulk_insert_csv(name, df, pk)
        else:
            bridge.batch_insert_ignore(name, df, pk)

    bridge.close()
    print("\nSync complete!")


if __name__ == "__main__":
    t = time.time()
    sync_all()
    print(f"Total time: {time.time()-t:.2f}s")