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
-- Single-row config: the two knobs that define the whole economic model.
CREATE TABLE IF NOT EXISTS fund_config (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    house_fee_pct       NUMERIC(5,4) NOT NULL DEFAULT 0.40,  -- house cut of each winning trade's profit
    gas_carveout_pct    NUMERIC(5,4) NOT NULL DEFAULT 0.10,  -- gas reserve, as a fraction of NET capital (not gross sent)
    min_deposit_net_usd NUMERIC(18,6) NOT NULL DEFAULT 200
);
INSERT INTO fund_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Running house (operator) fee balance. One row per accrual event so it's
-- auditable, not just a mutable counter.
CREATE TABLE IF NOT EXISTS house_ledger (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,          -- 'trade_fee' | 'withdrawal'
    trade_pnl_log_id BIGINT,                -- which closed trade this fee came from, if applicable
    amount_usd      NUMERIC(18,6) NOT NULL, -- positive = accrued to house, negative = house withdrew it
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Running gas reserve balance, funded by the 10% carve-out on deposits,
-- drawn down as the engine actually spends on network/priority fees.
CREATE TABLE IF NOT EXISTS gas_reserve_ledger (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,          -- 'deposit_carveout' | 'gas_spend'
    deposit_id      BIGINT REFERENCES deposits_withdrawals(id),
    amount_usd      NUMERIC(18,6) NOT NULL, -- positive = added to reserve, negative = spent
    note            TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE house_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE gas_reserve_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE fund_config ENABLE ROW LEVEL SECURITY;
-- No public policies on any of these three -- operator-only, read via the
-- service role (Telegram bot / admin scripts), never exposed to the
-- anon-key client the website uses. This is where "not on the front end"
-- is actually enforced, not just a UI choice.

-- deposits_withdrawals needs to record the gross amount sent vs. the net
-- that actually becomes shares, so the gas split is auditable per-deposit.
ALTER TABLE deposits_withdrawals ADD COLUMN IF NOT EXISTS gross_amount_usd NUMERIC(18,6);
ALTER TABLE deposits_withdrawals ADD COLUMN IF NOT EXISTS gas_carveout_usd NUMERIC(18,6) DEFAULT 0;
""")

conn.commit()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;")
print("Tables now in public schema:", [r[0] for r in cur.fetchall()])

cur.close()
conn.close()
