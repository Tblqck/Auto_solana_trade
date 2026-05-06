# sync_local_to_aws.py
import os
import sqlite3
import pandas as pd
from io import StringIO
import paramiko
from scp import SCPClient
import time

# ---------------- CONFIG ----------------
# Local DB on your Windows machine
LOCAL_DB = r"C:\Users\HP\Documents\sol_trade\db_files\dex_pipeline.db"

# AWS instance info
AWS_HOST = "3.26.3.145"
AWS_USER = "ec2-user"
AWS_KEY = r"C:\Users\HP\Documents\sol_trade\keys\instance_bd.pem"

# Remote paths on AWS
AWS_DB = "/home/ec2-user/sol_trade/db_files/dex_pipeline.db"
TMP_DIR = "/home/ec2-user/tmp"


TABLES_TO_SYNC = [
    {"name": "supported_tokens", "pk": ["Contract"]},
    {"name": "tokens", "pk": ["Contract"]},
    {"name": "ohlc_data", "pk": ["pair", "time"]},
]

# ---------------- SSH ----------------
def create_ssh_client():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=AWS_HOST, username=AWS_USER, key_filename=AWS_KEY)
    return ssh

def upload_file(ssh, local_path, remote_path):
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(local_path, remote_path)

# ---------------- DB ----------------
def get_local_df(table):
    conn = sqlite3.connect(LOCAL_DB)
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    conn.close()
    return df

def get_aws_existing_keys(ssh, table_name, pk_cols):
    pk_str = ", ".join(pk_cols)
    cmd = f"sqlite3 {AWS_DB} 'SELECT {pk_str} FROM {table_name}'"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode()
    if not out.strip():
        return set()
    keys = set(tuple(line.split("|")) for line in out.strip().split("\n"))
    return keys

def filter_new_rows(df, pk_cols, existing_keys):
    if df.empty or not existing_keys:
        return df
    mask = df.apply(lambda row: tuple(row[col] for col in pk_cols) not in existing_keys, axis=1)
    return df[mask]

def push_to_aws(ssh, df, table_name):
    if df.empty:
        print(f"⚠️ No new rows to insert into {table_name}. Skipping.")
        return
    tmp_csv = os.path.join("tmp_upload.csv")
    df.to_csv(tmp_csv, index=False)
    remote_csv = os.path.join(TMP_DIR, f"{table_name}.csv")
    upload_file(ssh, tmp_csv, remote_csv)
    cmd = f"sqlite3 {AWS_DB} <<'END_SQL'\n.mode csv\n.import {remote_csv} {table_name}\nEND_SQL"
    ssh.exec_command(cmd)
    os.remove(tmp_csv)
    print(f"✅ Inserted {len(df)} new rows into {table_name}")

# ---------------- PUBLIC FUNCTION ----------------
def sync_all():
    """Callable from another script to sync local DB to AWS"""
    ssh = create_ssh_client()
    print(f"✅ Connected to AWS: {AWS_HOST}\n")

    for tbl in TABLES_TO_SYNC:
        table_name = tbl["name"]
        pk_cols = tbl["pk"]
        print(f"📦 Syncing table: {table_name}")

        df_local = get_local_df(table_name)
        if df_local.empty:
            print(f"⚠️ Local table {table_name} is empty. Skipping.\n")
            continue

        existing_keys = get_aws_existing_keys(ssh, table_name, pk_cols)
        df_new = filter_new_rows(df_local, pk_cols, existing_keys)
        push_to_aws(ssh, df_new, table_name)
        print("")

    ssh.close()
    print("🎉 Sync complete!")

# ---------------- OPTIONAL: DELETE LOCAL DB ----------------
# def delete_local_db():
#     if os.path.exists(LOCAL_DB):
#         os.remove(LOCAL_DB)
#         print(f"⚠️ Local DB {LOCAL_DB} deleted!")
#     else:
#         print(f"Local DB {LOCAL_DB} does not exist. Nothing to delete.")

# ---------------- RUN DIRECTLY ----------------
if __name__ == "__main__":
    start = time.time()
    # delete_local_db()  # Uncomment if you want to reset local DB
    sync_all()
    end = time.time()
    print(f"⏱️ Total time: {end-start:.2f}s")
