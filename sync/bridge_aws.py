import os
import tempfile
import paramiko
import pandas as pd
from io import StringIO
from pathlib import Path


def _find_key(key_name):
    root = Path(__file__).resolve().parents[1]
    for base in [root, root.parent / "sol_trade"]:
        p = base / "keys" / key_name
        if p.exists():
            return p
    raise FileNotFoundError(f"SSH key '{key_name}' not found in keys/ folder")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEY_PATH = _find_key("sol_trade.pem")


class RemoteSQLiteBridge:
    def __init__(self):
        self.host = "54.206.109.26"
        self.user = "ec2-user"
        self.key_path = str(KEY_PATH)
        self.db_path = "/home/ec2-user/Auto_solana_trade/db_files/dex_pipeline.db"
        self.ssh = None
        self.tables = {}

    def connect(self):
        if not Path(self.key_path).exists():
            raise FileNotFoundError(f"SSH key not found: {self.key_path}")
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(hostname=self.host, username=self.user, key_filename=self.key_path)
        print(f"Connected to {self.host}")
        self._refresh_tables()

    def close(self):
        if self.ssh:
            self.ssh.close()
            print("SSH connection closed")

    def _exec_sql(self, sql, fetch=True):
        command = f'sqlite3 -header -csv {self.db_path} "{sql}"'
        stdin, stdout, stderr = self.ssh.exec_command(command)
        result = stdout.read().decode()
        error = stderr.read().decode()
        if error:
            print(f"Warning: {error.strip()}")
            return None
        if not fetch:
            return None
        if not result.strip():
            return pd.DataFrame()
        return pd.read_csv(StringIO(result))

    def _refresh_tables(self):
        df = self._exec_sql("SELECT name FROM sqlite_master WHERE type='table';")
        self.tables = {}
        if df is not None and not df.empty:
            for table in df["name"]:
                cols = self._exec_sql(f"PRAGMA table_info({table});")
                if cols is not None and not cols.empty:
                    self.tables[table] = list(cols["name"])
        print(f"Tables discovered: {list(self.tables.keys())}")

    def list_tables(self):
        return list(self.tables.keys())

    def describe_table(self, table):
        cols = self.tables.get(table)
        if not cols:
            print(f"Table {table} not found")
            return []
        print(f"{table}: {cols}")
        return cols

    def select(self, table, columns=None, limit=10, where=None):
        if table not in self.tables:
            print(f"Table {table} not found")
            return pd.DataFrame()
        col_str = ", ".join(columns) if columns else "*"
        sql = f"SELECT {col_str} FROM {table}"
        if where:
            conditions = []
            for k, v in where.items():
                v = str(v).replace("'", "''")
                conditions.append(f"{k}='{v}'")
            sql += " WHERE " + " AND ".join(conditions)
        sql += f" LIMIT {limit};"
        return self._exec_sql(sql)

    def insert(self, table, rows):
        if table not in self.tables:
            print(f"Table {table} not found")
            return
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            cols, vals = [], []
            for k, v in row.items():
                if k not in self.tables[table]:
                    continue
                cols.append(k)
                if v is None or pd.isna(v):
                    vals.append("NULL")
                elif isinstance(v, str):
                    vals.append("'" + v.replace("'", "''") + "'")
                else:
                    vals.append(str(v))
            sql = "INSERT INTO " + table + " (" + ", ".join(cols) + ") VALUES (" + ", ".join(vals) + ");"
            self._exec_sql(sql, fetch=False)
        print(f"Inserted {len(rows)} row(s) into {table}")

    def batch_insert_ignore(self, table, df, key_cols):
        if table not in self.tables:
            print(f"Table {table} not found")
            return
        key_str = ", ".join(key_cols)
        existing = self._exec_sql("SELECT " + key_str + " FROM " + table + ";")
        if existing is None or existing.empty:
            existing_keys = set()
        else:
            existing_keys = set(
                tuple(x) if len(key_cols) > 1 else x[0]
                for x in existing[key_cols].to_numpy()
            )
        def row_key(row):
            return tuple(row[k] for k in key_cols) if len(key_cols) > 1 else row[key_cols[0]]
        new_rows = [row for _, row in df.iterrows() if row_key(row) not in existing_keys]
        if not new_rows:
            print(f"{table}: no new rows to insert")
            return
        for row in new_rows:
            cols, vals = [], []
            for col in df.columns:
                if col not in self.tables[table]:
                    continue
                val = row[col]
                cols.append(col)
                if val is None or pd.isna(val):
                    vals.append("NULL")
                elif isinstance(val, str):
                    vals.append("'" + val.replace("'", "''") + "'")
                else:
                    vals.append(str(val))
            sql = "INSERT INTO " + table + " (" + ", ".join(cols) + ") VALUES (" + ", ".join(vals) + ");"
            self._exec_sql(sql, fetch=False)
        print(f"Inserted {len(new_rows)} new rows into {table}")

    def bulk_insert_csv(self, table, df, key_cols, tmp_dir="/home/ec2-user/tmp"):
        if table not in self.tables:
            print(f"Table {table} not found")
            return
        key_str = ", ".join(key_cols)
        existing = self._exec_sql("SELECT " + key_str + " FROM " + table + ";")
        if existing is not None and not existing.empty:
            if len(key_cols) == 1:
                k = key_cols[0]
                existing_keys = set(existing[k].astype(str).tolist())
                new_rows = df[~df[k].astype(str).isin(existing_keys)]
            else:
                existing_keys = set(
                    tuple(str(v) for v in row)
                    for row in existing[key_cols].to_numpy()
                )
                new_rows = df[
                    ~df.apply(
                        lambda r: tuple(str(r[k]) for k in key_cols) in existing_keys,
                        axis=1
                    )
                ]
        else:
            new_rows = df.copy()
        if new_rows.empty:
            print(f"{table}: no new rows to insert")
            return
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        ) as f:
            new_rows.to_csv(f, index=False)
            tmp_local = f.name
        try:
            self.ssh.exec_command("mkdir -p " + tmp_dir)
            remote_csv = tmp_dir + "/" + table + "_sync.csv"
            sftp = self.ssh.open_sftp()
            sftp.put(tmp_local, remote_csv)
            sftp.close()
            py_cmd = (
                "import pandas as pd, sqlite3; "
                "df=pd.read_csv('" + remote_csv + "'); "
                "conn=sqlite3.connect('" + self.db_path + "'); "
                "df.to_sql('" + table + "', conn, if_exists='append', index=False); "
                "conn.close(); "
                "print(len(df))"
            )
            _, stdout, stderr = self.ssh.exec_command('python3 -c "' + py_cmd + '"')
            count = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            if err:
                print(f"Remote error on {table}: {err}")
            else:
                print(f"Bulk-inserted {count} rows into {table}")
        finally:
            os.unlink(tmp_local)

    def batch_delete_not_in(self, table, column, keep_list, batch_size=500):
        if not keep_list:
            self._exec_sql("DELETE FROM " + table + ";", fetch=False)
            print(f"{table}: wiped (keep list empty)")
            return
        for i in range(0, len(keep_list), batch_size):
            batch = keep_list[i:i + batch_size]
            values = ",".join("'" + str(x).replace("'", "''") + "'" for x in batch)
            sql = "DELETE FROM " + table + " WHERE " + column + " NOT IN (" + values + ");"
            self._exec_sql(sql, fetch=False)
        print(f"Cleaned {table}")

    def cleanup_tokens_and_ohlc(self):
        df = self.select("ai_thought", columns=["pair_id"], limit=200000)
        if df.empty:
            print("ai_thought empty, skipping cleanup")
            return
        pair_ids = df["pair_id"].dropna().unique().tolist()
        print(f"Preserving {len(pair_ids)} pair_ids")
        self.batch_delete_not_in("tokens", "contract", pair_ids)
        self.batch_delete_not_in("supported_tokens", "contract", pair_ids)
        self.batch_delete_not_in("ohlc_data", "pair_id", pair_ids)


if __name__ == "__main__":
    bridge = RemoteSQLiteBridge()
    bridge.connect()
    bridge.list_tables()
    bridge.describe_table("tokens")
    print(bridge.select("tokens", limit=5))
    bridge.close()
