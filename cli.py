#!/usr/bin/env python3
"""
sol_trade command pipeline
Usage:
  python cli.py liquidate    — sell every open position immediately
  python cli.py state        — show wallet balances + open positions
"""
import sys


def cmd_liquidate():
    from core.db_utils import get_db_connection
    from signals.watcher_core import queue_trade, trade_engine_status, start_trade_engine

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT pair_id, contract FROM live_trades WHERE status = 'OPEN'"
    )
    open_trades = cur.fetchall()
    conn.close()

    if not open_trades:
        print("[CLI] No open positions to liquidate.")
        return

    print(f"\n[CLI] LIQUIDATE — queuing SELL for {len(open_trades)} position(s):")
    for pair_id, contract in open_trades:
        queue_trade(contract, 0, reason="LIQUIDATE")
        print(f"  SELL queued [{pair_id}] {contract}")

    print()
    if not trade_engine_status():
        print("[CLI] Launching trade engine to execute...")
        start_trade_engine()
    else:
        print("[CLI] Trade engine already running — it will pick up the queued sells.")


def cmd_state():
    from core.db_utils import get_db_connection
    from wallet.wallet_state import get_wallet_state

    print("\n[CLI] Fetching on-chain wallet state...\n")
    wallet = get_wallet_state()

    usdc_balance = next(
        (t["amount"] for t in wallet.get("tokens", [])
         if t["mint"] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
        0.0,
    )

    print("=" * 52)
    print("  WALLET STATE")
    print("=" * 52)
    print(f"  SOL balance : {wallet.get('sol_balance', 0):.6f} SOL"
          f"  (${wallet.get('sol_usd', 0):.2f})")
    print(f"  USDC balance: ${usdc_balance:.4f}")
    print(f"  Total USD   : ${wallet.get('total_usd', 0):.4f}")

    other_tokens = [
        t for t in wallet.get("tokens", [])
        if t["mint"] != "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    ]
    if other_tokens:
        print(f"\n  Other tokens ({len(other_tokens)}):")
        for t in other_tokens:
            usd = t.get("usd_value")
            usd_str = f"  ${usd:.4f}" if usd is not None else "  (no price)"
            print(f"    {t['mint'][:20]}...  {t['amount']:.6f}{usd_str}")

    print()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT lt.pair_id, lt.contract, lt.entry_price, lt.entry_time,
               trs.current_price, trs.stop_price, trs.peak_price, trs.trigger_type
        FROM live_trades lt
        LEFT JOIN trade_risk_state trs ON lt.pair_id = trs.pair_id
        WHERE lt.status = 'OPEN'
        ORDER BY lt.entry_time ASC
    """)
    positions = cur.fetchall()
    conn.close()

    if not positions:
        print("  No open positions.\n")
        return

    print(f"  OPEN POSITIONS ({len(positions)})")
    print("-" * 52)
    for pair_id, contract, entry_price, entry_time, current, stop, peak, trigger in positions:
        entry_price = float(entry_price or 0)
        current     = float(current or 0)
        stop        = float(stop or 0)
        peak        = float(peak or 0)

        pnl_pct = ((current - entry_price) / entry_price * 100) if entry_price > 0 else 0
        stop_dist = ((current - stop) / current * 100) if current > 0 else 0
        pnl_sign = "+" if pnl_pct >= 0 else ""

        print(f"  {pair_id}")
        print(f"    contract : {contract}")
        print(f"    entry    : {entry_price:.8f}  (at {entry_time})")
        print(f"    current  : {current:.8f}  ({pnl_sign}{pnl_pct:.2f}% P&L)")
        print(f"    peak     : {peak:.8f}")
        print(f"    stop     : {stop:.8f}  ({stop_dist:.2f}% below current)")
        if trigger:
            print(f"    trigger  : {trigger}")
        print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lstrip("/").lower()

    if cmd == "liquidate":
        cmd_liquidate()
    elif cmd == "state":
        cmd_state()
    else:
        print(f"[CLI] Unknown command: {sys.argv[1]}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
