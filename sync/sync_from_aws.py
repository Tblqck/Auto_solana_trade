# sync_from_aws.py
import sqlite3
import os
import pandas as pd
from bridge_aws import RemoteSQLiteBridge

# ---------------- CONFIG ----------------
LOCAL_ARCHIVE_DB = "db_files/dex_pipeline_archive.db"
TABLES_TO_SYNC = ["tokens", "supported_tokens", "ohlc_data"]

# ---------------- LOCAL DB CONNECTION ----------------
def get_local_conn():
    os.makedirs(os.path.dirname(LOCAL_ARCHIVE_DB), exist_ok=True)
    return sqlite3.connect(LOCAL_ARCHIVE_DB)

# ---------------- PRIMARY KEY MAPPING ----------------
def get_primary_key(table_name):
    pk_map = {
        "tokens": "Contract",
        "supported_tokens": "Contract",
        "ohlc_data": ("pair_id", "time")
    }
    return pk_map[table_name]

# ---------------- SYNC FUNCTION ----------------
def sync_table(bridge, table_name):
    print(f"\n🔄 Syncing table: {table_name}")

    # Fetch all rows from AWS
    remote_df = bridge.select(table_name, limit=1000000)
    if remote_df.empty:
        print(f"⚠️ No data found on AWS for {table_name}")
        return

    conn = get_local_conn()
    pk = get_primary_key(table_name)

    # Get existing keys from local DB
    if isinstance(pk, tuple):
        local_keys_df = pd.read_sql_query(f"SELECT {', '.join(pk)} FROM {table_name}", conn)
        local_keys_set = set([tuple(x) for x in local_keys_df.to_numpy()])
        remote_keys_set = [tuple(x) for x in remote_df[list(pk)].to_numpy()]
        # Only new rows
        new_rows = remote_df[[x not in local_keys_set for x in remote_keys_set]]
    else:
        local_keys_df = pd.read_sql_query(f"SELECT {pk} FROM {table_name}", conn)
        local_keys_set = set(local_keys_df[pk].tolist())
        new_rows = remote_df[~remote_df[pk].isin(local_keys_set)]

    if new_rows.empty:
        print(f"✅ No new rows to insert for {table_name}")
        conn.close()
        return

    # Insert new rows
    new_rows.to_sql(table_name, conn, if_exists="append", index=False)
    print(f"✅ Inserted {len(new_rows)} new row(s) into {table_name}")
    conn.close()

# ---------------- SYNC ALL TABLES FUNCTION ----------------
def sync_all_tables():
    """
    Connects to AWS and syncs all tables to the local archive DB.
    Can be imported and called from another Python script.
    """
    bridge = RemoteSQLiteBridge()
    bridge.connect()

    for table in TABLES_TO_SYNC:
        sync_table(bridge, table)

    bridge.close()
    print("\n🎉 All tables synced successfully!")

# ---------------- RUN AS SCRIPT ----------------
if __name__ == "__main__":
    sync_all_tables()
