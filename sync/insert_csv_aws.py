# insert_csv_aws.py
import pandas as pd
import sqlite3
import sys

csv_file = sys.argv[1]
table_name = sys.argv[2]
db_file = sys.argv[3]

df = pd.read_csv(csv_file)

conn = sqlite3.connect(db_file)
df.to_sql(table_name, conn, if_exists='append', index=False)
conn.close()

print(f"✅ Inserted {len(df)} rows into {table_name}")
# __ this is used expressley on aws to bridge