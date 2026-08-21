# sync/supabase_bridge.py
"""
Runs ON the EC2 instance, called from the live trading pipeline. Writes
directly to Supabase via a privileged Postgres connection (Transaction_pooler
in .env) -- NOT the anon-key/RLS path the website uses. The engine is a
trusted backend service, not a client, so this deliberately bypasses RLS to
write nav_snapshots, house_ledger, gas_reserve_ledger, and trade_feed.

This is what makes "the site always matches the engine" true: the site
never computes or guesses any of these numbers, it only ever reads what
this module wrote.
"""
import os
from datetime import datetime, timezone

import psycopg2
from dotenv import load_dotenv

load_dotenv()

_CONN = None


def _connect():
    global _CONN
    if _CONN is not None and _CONN.closed == 0:
        return _CONN
    db_string = os.getenv("Transaction_pooler")
    body = db_string.split("://", 1)[1]
    creds_part, host_part = body.rsplit("@", 1)
    user, password = creds_part.split(":", 1)
    host_port, dbname = host_part.split("/", 1)
    host, port = host_port.split(":")
    _CONN = psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user, password=password,
        sslmode="require", connect_timeout=10,
    )
    return _CONN


def _fund_config() -> dict:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT house_fee_pct, gas_carveout_pct, min_deposit_net_usd FROM fund_config WHERE id=1")
    row = cur.fetchone()
    return {"house_fee_pct": float(row[0]), "gas_carveout_pct": float(row[1]), "min_deposit_net_usd": float(row[2])}


def record_house_fee(trade_pnl_log_id, amount_usd: float, note: str = None):
    """40% of a winning trade's realized profit, accrued to the house ledger."""
    if amount_usd <= 0:
        return
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO house_ledger (source, trade_pnl_log_id, amount_usd, note) VALUES ('trade_fee', %s, %s, %s)",
            (trade_pnl_log_id, amount_usd, note),
        )
        conn.commit()
    except Exception as e:
        print(f"[SupabaseBridge] record_house_fee failed (non-fatal): {e}")


def record_gas_spend(amount_usd: float, note: str = None):
    """Draw down the gas reserve as the engine actually spends on network/priority fees."""
    if amount_usd <= 0:
        return
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gas_reserve_ledger (source, amount_usd, note) VALUES ('gas_spend', %s, %s)",
            (-abs(amount_usd), note),
        )
        conn.commit()
    except Exception as e:
        print(f"[SupabaseBridge] record_gas_spend failed (non-fatal): {e}")


def push_trade_feed_event(kind: str, market: str, reason: str = None, amount_usd: float = None, pnl_usd: float = None):
    """kind: 'buy' | 'sell' | 'halt' | 'resume' -- powers the site's Live Activity page."""
    try:
        conn = _connect()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO trade_feed (kind, market, reason, amount_usd, pnl_usd) VALUES (%s, %s, %s, %s, %s)",
            (kind, market, reason, amount_usd, pnl_usd),
        )
        conn.commit()
    except Exception as e:
        print(f"[SupabaseBridge] push_trade_feed_event failed (non-fatal): {e}")


def push_nav_snapshot():
    """
    Computes the investor-facing NAV and writes a fresh nav_snapshots row.
    investor_pool = raw wallet total - house's accrued (unwithdrawn) fees
                    - unspent gas reserve.
    Called on a timer (main.py) and after any event that actually changes
    the pool's value (a confirmed deposit/withdrawal, a closed trade).
    """
    try:
        from wallet.wallet_state import get_wallet_state
        raw_total_usd = get_wallet_state().get("total_usd", 0.0)

        conn = _connect()
        cur = conn.cursor()

        cur.execute("SELECT COALESCE(SUM(amount_usd), 0) FROM house_ledger")
        house_accrued = float(cur.fetchone()[0])

        cur.execute("SELECT COALESCE(SUM(amount_usd), 0) FROM gas_reserve_ledger")
        gas_reserve = float(cur.fetchone()[0])

        cur.execute("""
            SELECT COALESCE(SUM(CASE WHEN direction='deposit' THEN shares ELSE -shares END), 0)
            FROM deposits_withdrawals WHERE status='confirmed'
        """)
        total_shares = float(cur.fetchone()[0])

        investor_pool_usd = raw_total_usd - house_accrued - gas_reserve
        share_price = (investor_pool_usd / total_shares) if total_shares > 0 else 1.00

        cur.execute(
            "INSERT INTO nav_snapshots (total_pool_usd, total_shares, share_price) VALUES (%s, %s, %s)",
            (investor_pool_usd, total_shares, share_price),
        )
        conn.commit()
        print(f"[SupabaseBridge] NAV pushed: pool=${investor_pool_usd:.4f} shares={total_shares:.4f} price=${share_price:.6f}")
    except Exception as e:
        print(f"[SupabaseBridge] push_nav_snapshot failed (non-fatal): {e}")


if __name__ == "__main__":
    push_nav_snapshot()
