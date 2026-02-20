# trade_signal_builder.py

from db_utils import get_db_connection
from allocation_manager import get_dynamic_allocation

def fetch_pending_trades():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, contract, decision, time_queued
        FROM pending_trades
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def contract_in_live_trade(contract):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 1
        FROM live_trades
        WHERE contract=?
        LIMIT 1
    """, (contract,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def build_trade_signals():
    pending = fetch_pending_trades()
    sell_signals = []
    buy_signals = []

    for trade_id, contract, decision, _ in pending:
        decision = int(decision)

        if decision == -1:  # SELL
            sell_signals.append({
                "type": "SELL",
                "token_mint": contract
            })
            continue

        if decision == 1:  # BUY
            if contract_in_live_trade(contract):
                continue
            allocation = get_dynamic_allocation(hours=12)
            if allocation <= 0:
                continue
            buy_signals.append({
                "type": "BUY",
                "token_mint": contract,
                "amount": float(allocation)
            })

    # BUY first, then SELL (matching your desired format)
    trade_signals = buy_signals + sell_signals
    return trade_signals


if __name__ == "__main__":
    trade_signals = build_trade_signals()
    print("🔹 Trade signals ready for executor:")
    print(trade_signals)
