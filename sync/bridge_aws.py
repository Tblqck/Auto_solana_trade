import paramiko
import pandas as pd
from io import StringIO
from pathlib import Path


# -------------------------------------------------
# project root resolver
# -------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
KEY_PATH = PROJECT_ROOT / "keys" / "instance_bd.pem"


class RemoteSQLiteBridge:
    def __init__(self):
        # ---------------- AWS CONFIG ----------------
        self.host = "3.26.3.145"
        self.user = "ec2-user"

        # FIXED (no hard path anymore)
        self.key_path = str(KEY_PATH)

        self.db_path = "/home/ec2-user/db_files/dex_pipeline.db"

        self.ssh = None
        self.tables = {}  # table_name -> list of columns

    # ---------------- SSH ----------------
    def connect(self):
        if not Path(self.key_path).exists():
            raise FileNotFoundError(f"SSH key not found: {self.key_path}")

        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            hostname=self.host,
            username=self.user,
            key_filename=self.key_path
        )
        print(f"✅ Connected to {self.host}")
        self._refresh_tables()

    def close(self):
        if self.ssh:
            self.ssh.close()
            print("✅ SSH connection closed")

    # ---------------- CORE SQL EXEC ----------------
    def _exec_sql(self, sql, fetch=True):
        command = f'sqlite3 -header -csv {self.db_path} "{sql}"'
        stdin, stdout, stderr = self.ssh.exec_command(command)

        result = stdout.read().decode()
        error = stderr.read().decode()

        if error:
            print("⚠️ Error:", error.strip())
            return None

        if not fetch:
            return None

        if not result.strip():
            return pd.DataFrame()

        return pd.read_csv(StringIO(result))

    # ---------------- TABLE DISCOVERY ----------------
    def _refresh_tables(self):
        df = self._exec_sql("SELECT name FROM sqlite_master WHERE type='table';")
        self.tables = {}

        if df is not None and not df.empty:
            for table in df["name"]:
                cols = self._exec_sql(f"PRAGMA table_info({table});")
                if cols is not None and not cols.empty:
                    self.tables[table] = list(cols["name"])

        print(f"📋 Tables discovered: {list(self.tables.keys())}")

    def list_tables(self):
        return list(self.tables.keys())

    def describe_table(self, table):
        cols = self.tables.get(table)
        if not cols:
            print(f"⚠️ Table {table} not found")
            return []
        print(f"📐 {table}: {cols}")
        return cols

    # ---------------- SELECT ----------------
    def select(self, table, columns=None, limit=10, where=None):
        if table not in self.tables:
            print(f"⚠️ Table {table} not found")
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

    # ---------------- SIMPLE INSERT ----------------
    def insert(self, table, rows):
        if table not in self.tables:
            print(f"⚠️ Table {table} not found")
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
                    safe_v = v.replace("'", "''")
                    vals.append(f"'{safe_v}'")
                else:
                    vals.append(str(v))

            sql = f"""
            INSERT INTO {table} ({', '.join(cols)})
            VALUES ({', '.join(vals)});
            """
            self._exec_sql(sql, fetch=False)

        print(f"✅ Inserted {len(rows)} row(s) into {table}")

    # ---------------- SAFE BATCH INSERT ----------------
    def batch_insert_ignore(self, table, df, key_cols):
        if table not in self.tables:
            print(f"⚠️ Table {table} not found")
            return

        key_str = ", ".join(key_cols)
        existing = self._exec_sql(f"SELECT {key_str} FROM {table};")

        if existing is None or existing.empty:
            existing_keys = set()
        else:
            existing_keys = set(
                tuple(x) if len(key_cols) > 1 else x[0]
                for x in existing[key_cols].to_numpy()
            )

        def row_key(row):
            return tuple(row[k] for k in key_cols) if len(key_cols) > 1 else row[key_cols[0]]

        new_rows = [
            row for _, row in df.iterrows()
            if row_key(row) not in existing_keys
        ]

        if not new_rows:
            print(f"✅ {table}: no new rows to insert")
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
                    safe_val = val.replace("'", "''")
                    vals.append(f"'{safe_val}'")
                else:
                    vals.append(str(val))

            sql = f"""
            INSERT INTO {table} ({', '.join(cols)})
            VALUES ({', '.join(vals)});
            """
            self._exec_sql(sql, fetch=False)

        print(f"✅ Inserted {len(new_rows)} new rows into {table}")

    # ---------------- DELETE HELPERS ----------------
    def batch_delete_not_in(self, table, column, keep_list, batch_size=500):
        if not keep_list:
            self._exec_sql(f"DELETE FROM {table};", fetch=False)
            print(f"⚠️ {table}: wiped (keep list empty)")
            return

        for i in range(0, len(keep_list), batch_size):
            batch = keep_list[i:i + batch_size]
            values = ",".join("'" + str(x).replace("'", "''") + "'" for x in batch)
            sql = f"DELETE FROM {table} WHERE {column} NOT IN ({values});"
            self._exec_sql(sql, fetch=False)

        print(f"🧹 Cleaned {table}")

    # ---------------- AI THOUGHT CLEANUP ----------------
    def cleanup_tokens_and_ohlc(self):
        df = self.select("ai_thought", columns=["pairid"], limit=200000)
        if df.empty:
            print("⚠️ ai_thought empty, skipping cleanup")
            return

        pair_ids = df["pairid"].dropna().unique().tolist()
        print(f"🧩 Preserving {len(pair_ids)} pair_ids")

        self.batch_delete_not_in("tokens", "Token", pair_ids)
        self.batch_delete_not_in("supported_tokens", "Contract", pair_ids)
        self.batch_delete_not_in("ohlc_data", "pair_id", pair_ids)


# ---------------- TEST ----------------
if __name__ == "__main__":
    bridge = RemoteSQLiteBridge()
    bridge.connect()

    bridge.list_tables()
    bridge.describe_table("tokens")

    print(bridge.select("tokens", limit=5))

    bridge.close()
