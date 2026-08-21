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
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email TEXT,
    payout_wallet TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deposits_withdrawals (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    direction TEXT NOT NULL CHECK (direction IN ('deposit', 'withdrawal')),
    amount_usd NUMERIC(18,6) NOT NULL,
    share_price_at_tx NUMERIC(18,6) NOT NULL,
    shares NUMERIC(18,6) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'rejected')),
    tx_signature TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS nav_snapshots (
    id BIGSERIAL PRIMARY KEY,
    total_pool_usd NUMERIC(18,6) NOT NULL,
    total_shares NUMERIC(18,6) NOT NULL,
    share_price NUMERIC(18,6) NOT NULL,
    taken_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_feed (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('buy', 'sell', 'halt', 'resume')),
    market TEXT,
    reason TEXT,
    amount_usd NUMERIC(18,6),
    pnl_usd NUMERIC(18,6),
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Row Level Security: users can only ever see/touch their own rows.
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE deposits_withdrawals ENABLE ROW LEVEL SECURITY;
ALTER TABLE nav_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_feed ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own profile" ON profiles;
CREATE POLICY "own profile" ON profiles FOR ALL USING (auth.uid() = id);

DROP POLICY IF EXISTS "own transactions" ON deposits_withdrawals;
CREATE POLICY "own transactions" ON deposits_withdrawals FOR ALL USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "public read nav" ON nav_snapshots;
CREATE POLICY "public read nav" ON nav_snapshots FOR SELECT USING (true);

DROP POLICY IF EXISTS "public read feed" ON trade_feed;
CREATE POLICY "public read feed" ON trade_feed FOR SELECT USING (true);
""")

conn.commit()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;")
print("Tables now in public schema:", [r[0] for r in cur.fetchall()])

cur.close()
conn.close()
