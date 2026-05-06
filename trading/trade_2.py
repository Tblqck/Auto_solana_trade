# trade_signal_builder.py
from datetime import datetime, timezone, timedelta

from core.db_utils import get_db_connection
from wallet.allocation_manager import get_dynamic_allocation, claim_recycled_slot
from wallet.wallet_state import get_sol_balance, get_token_price_usd, get_token_balance

MAX_SIGNAL_AGE_SECONDS = 60
MIN_TRADE_USDC         = 1.0

USDC_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT       = "So11111111111111111111111111111111111111112"
SOL_RESERVE_USD = 2.0   # floor — trigger refill below this
SOL_TARGET_USD  = 3.5   # top-up target — buffer so we don't refill every cycle


def _sol_refill_signal() -> dict | None:
    """
    Check on-chain SOL value. If below SOL_RESERVE_USD, return a REFILL signal
    that will swap enough USDC to bring SOL up to SOL_TARGET_USD.
    Returns None if SOL is fine or there isn't enough USDC to bother.
    """
    sol_usd = get_sol_balance() * get_token_price_usd("solana")
    if sol_usd >= SOL_RESERVE_USD:
        return None

    usdc_needed  = SOL_TARGET_USD - sol_usd
    usdc_token   = get_token_balance(USDC_MINT)
    usdc_avail   = usdc_token["amount"] if usdc_token else 0.0
    # Keep at least $0.50 USDC liquid after the refill
    usdc_to_swap = min(usdc_needed, max(0.0, usdc_avail - 0.50))

    if usdc_to_swap < MIN_TRADE_USDC:
        print(f"[Trade] REFILL: SOL low (${sol_usd:.2f}) but not enough USDC "
              f"(${usdc_avail:.2f}) to refill — skipping")
        return None

    print(f"[Trade] REFILL triggered: SOL ${sol_usd:.2f} < ${SOL_RESERVE_USD:.2f} "
          f"-> swapping ${usdc_to_swap:.4f} USDC for SOL (target ${SOL_TARGET_USD:.2f})")
    return {
        "type":       "REFILL",
        "token_mint": SOL_MINT,
        "amount":     round(usdc_to_swap, 4),
    }


def fetch_pending_trades():
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, contract, decision, time_queued
        FROM pending_trades
        ORDER BY id ASC
        LIMIT 100
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def purge_stale_pending():
    conn = get_db_connection()
    cur  = conn.cursor()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS)
    cur.execute("DELETE FROM pending_trades WHERE time_queued < ?", (cutoff,))
    purged = cur.rowcount
    conn.commit()
    conn.close()
    if purged:
        print(f"[Trade] Purged {purged} stale pending trade(s) (>{MAX_SIGNAL_AGE_SECONDS}s old)")


def contract_in_live_trade(contract: str) -> bool:
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT 1 FROM live_trades WHERE contract=? LIMIT 1", (contract,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def build_trade_signals() -> tuple[list, dict]:
    """Return (signals, pending_map) where pending_map is {contract: pending_id}.
    Both are built from the same DB fetch to avoid a double-query race window."""
    purge_stale_pending()

    # SOL refill has highest priority — must fire before any other trade
    refill = _sol_refill_signal()

    pending      = fetch_pending_trades()
    # Build the map here so trade.py doesn't need a second fetch
    pending_map  = {contract: trade_id for trade_id, contract, _, _ in pending}

    sell_signals = []
    buy_signals  = []

    for _trade_id, contract, decision, _ in pending:
        decision = int(decision)

        if decision == 0:  # SELL
            sell_signals.append({"type": "SELL", "token_mint": contract})
            continue

        if decision == 1:  # BUY
            if contract_in_live_trade(contract):
                print(f"[Trade] Skip BUY {contract[:8]}... already in live_trades")
                continue

            amount = claim_recycled_slot()
            source = "recycled"

            if amount < MIN_TRADE_USDC:
                amount = get_dynamic_allocation(hours=12)
                source = "planned"

            if amount < MIN_TRADE_USDC:
                print(f"[Trade] Skip BUY {contract[:8]}... allocation ${amount:.4f} < min")
                continue

            print(f"[Trade] BUY {contract[:8]}... via {source} slot -> ${amount:.4f}")
            buy_signals.append({
                "type":       "BUY",
                "token_mint": contract,
                "amount":     float(amount),
            })

    # REFILL first (gas), then SELLs (free capital), then BUYs
    signals = ([refill] if refill else []) + sell_signals + buy_signals
    return signals, pending_map


if __name__ == "__main__":
    signals = build_trade_signals()
    print("Trade signals ready:")
    print(signals)
