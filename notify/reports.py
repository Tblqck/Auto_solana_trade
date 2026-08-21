import threading
from datetime import datetime, timezone

from notify.telegram import send

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# ── Thread-safe DataLoop stats accumulator ────────────────────────────────────
_stats_lock = threading.Lock()
_dl_runs    = 0
_dl_pairs   = 0
_dl_rows    = 0


def accumulate_dataloop_stats(pairs_checked: int, rows_inserted: int):
    global _dl_runs, _dl_pairs, _dl_rows
    with _stats_lock:
        _dl_runs  += 1
        _dl_pairs += pairs_checked
        _dl_rows  += rows_inserted


def _pop_dataloop_stats() -> dict:
    global _dl_runs, _dl_pairs, _dl_rows
    with _stats_lock:
        snap = {"runs": _dl_runs, "pairs": _dl_pairs, "rows": _dl_rows}
        _dl_runs = _dl_pairs = _dl_rows = 0
    return snap


# ── Hourly DataLoop digest ─────────────────────────────────────────────────────
def send_hourly_dataloop_report():
    stats = _pop_dataloop_stats()
    now   = datetime.now(timezone.utc).strftime("%H:%M UTC")
    text  = (
        f"<b>DataLoop — 1h Digest ({now})</b>\n\n"
        f"Cycles completed: {stats['runs']}\n"
        f"Pairs checked:    {stats['pairs']:,}\n"
        f"OHLC rows saved:  {stats['rows']:,}"
    )
    send(text)
    print(f"[Notify] DataLoop digest sent ({stats['runs']} cycles, {stats['rows']} rows)")


# ── Hourly wallet report ───────────────────────────────────────────────────────
def send_hourly_wallet_report():
    from wallet.wallet_state import get_wallet_state
    from core.db_utils import get_db_connection

    now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        wallet = get_wallet_state()
    except Exception as e:
        send(f"<b>Wallet Report ({now_str})</b>\n\nFailed to fetch wallet: {e}")
        return

    sol_balance = wallet.get("sol_balance", 0.0)
    sol_usd     = wallet.get("sol_usd", 0.0)
    total_usd   = wallet.get("total_usd", 0.0)
    usdc = next(
        (t["amount"] for t in wallet.get("tokens", []) if t["mint"] == USDC_MINT),
        0.0,
    )

    try:
        conn = get_db_connection()
        cur  = conn.cursor()

        cur.execute(
            "SELECT contract, entry_price, entry_time FROM live_trades ORDER BY entry_time ASC"
        )
        live_rows = cur.fetchall()

        cur.execute("""
            SELECT slot_type, COUNT(*) FROM allocation_slots
            WHERE stop_timestamp > ?
            GROUP BY slot_type
        """, (now_iso,))
        slot_counts    = dict(cur.fetchall())
        planned_slots  = slot_counts.get("planned", 0)
        recycled_slots = slot_counts.get("recycled", 0)

        conn.close()
    except Exception:
        live_rows      = []
        planned_slots  = 0
        recycled_slots = 0

    lines = [f"<b>Wallet Report — {now_str}</b>\n"]
    lines.append(f"SOL:   {sol_balance:.4f} SOL  (~${sol_usd:.2f})")
    lines.append(f"USDC:  ${usdc:.2f}")
    lines.append(f"Total: ${total_usd:.2f}\n")
    lines.append(f"Open positions: {len(live_rows)}")

    for contract, entry_price, entry_time in live_rows:
        short     = contract[:16] + "..."
        price_str = f"${entry_price:.8f}" if entry_price else "unknown"
        lines.append(f"  {short}  entry {price_str}")

    lines.append(f"\nSlots: {planned_slots}/5 planned | {recycled_slots} recycled available")

    send("\n".join(lines))
    print("[Notify] Wallet report sent")


# ── Per-event notifications ────────────────────────────────────────────────────
def notify_trade_entry(token_mint: str, amount_usdc: float, entry_price: float):
    short = token_mint[:16] + "..."
    price_str = f"${entry_price:.8f}" if entry_price else "unknown"
    text  = (
        f"<b>BUY Executed</b>\n\n"
        f"Token:  {short}\n"
        f"Amount: ${amount_usdc:.2f} USDC\n"
        f"Price:  {price_str}"
    )
    send(text)


def notify_trade_exit(token_mint: str, usdc_gained: float, usdc_spent: float = 0.0, exit_reason: str = None):
    short   = token_mint[:16] + "..."
    pnl     = usdc_gained - usdc_spent if usdc_spent > 0 else usdc_gained
    sign    = "+" if pnl >= 0 else ""
    outcome = "PROFIT" if pnl >= 0 else "LOSS"
    spent_line  = f"Spent:     ${usdc_spent:.2f} USDC\n" if usdc_spent > 0 else ""
    reason_line = f"Reason:    {exit_reason}\n" if exit_reason else ""
    text    = (
        f"<b>SELL Executed — {outcome}</b>\n\n"
        f"Token:     {short}\n"
        f"Recovered: ${usdc_gained:.2f} USDC\n"
        f"{spent_line}"
        f"{reason_line}"
        f"P&amp;L:       {sign}${pnl:.2f}"
    )
    send(text)


def log_trade_pnl(contract: str, usdc_spent: float, usdc_gained: float, exit_reason: str = None):
    """Persist realized P&L for a confirmed SELL to trade_pnl_log — powers /pnl's
    'which token contributed to growth' breakdown. Best-effort, never raises.
    Returns the inserted row id (or None on failure) so callers can link a
    house-fee ledger entry to the exact trade it came from."""
    try:
        from core.db_utils import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM supported_tokens WHERE contract=?", (contract,))
        row = cur.fetchone()
        symbol = row[0] if row and row[0] else None
        cur.execute("""
            INSERT INTO trade_pnl_log (contract, symbol, usdc_spent, usdc_gained, realized_pnl, exit_reason, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            contract, symbol, usdc_spent, usdc_gained, usdc_gained - usdc_spent,
            exit_reason, datetime.now(timezone.utc).isoformat(),
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id
    except Exception as e:
        print(f"[Notify] log_trade_pnl failed (non-fatal): {e}")
        return None


def notify_sol_low(sol_usd: float):
    text = (
        f"<b>SOL Low — Mid-Window Refill Executed</b>\n\n"
        f"SOL dropped to <b>${sol_usd:.2f}</b>\n"
        f"Auto-refill to $3.00 target triggered.\n"
        f"Cost deducted from unused trade slots."
    )
    send(text)
    print(f"[Notify] Mid-window SOL refill notification sent (${sol_usd:.2f})")


def notify_recycled_slot(amount_usdc: float):
    text = (
        f"<b>Recycled Slot Created</b>\n\n"
        f"USDC recovered: ${amount_usdc:.2f}\n"
        f"Ready for next BUY cycle"
    )
    send(text)
