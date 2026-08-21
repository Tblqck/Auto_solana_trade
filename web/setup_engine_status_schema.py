import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

db_string = os.getenv("Transaction_pooler")
body = db_string.split("://", 1)[1]
creds_part, host_part = body.rsplit("@", 1)
user, password = creds_part.split(":", 1)
host_port, dbname = host_part.split("/", 1)
host, port = host_port.split(":")

conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password, sslmode="require")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS engine_status (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    status      TEXT NOT NULL DEFAULT 'stopped' CHECK (status IN ('running', 'stopped')),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO engine_status (id, status) VALUES (1, 'stopped') ON CONFLICT (id) DO NOTHING;

ALTER TABLE engine_status ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "public read engine status" ON engine_status;
CREATE POLICY "public read engine status" ON engine_status FOR SELECT USING (true);
""")

conn.commit()
print("engine_status table ready")
cur.close()
conn.close()
