# trade_orch_pipeline.py
import time
from uuid import uuid4

from trading.trade_shadow import handle_signal, USDC_MINT, SOL_MINT
from wallet.wallet_state import get_wallet_state, get_token_balance, save_wallet_db
from wallet.allocation_manager import register_recycled_slot
from trading.trade_tracker import check_trade_status

TRADE_INTERVAL    = 3     # seconds between trades
MAX_POLL_ATTEMPTS = 15
POLL_WAIT_TIME    = 2     # seconds between polls
MAX_ATTEMPTS      = 3     # re-quote/re-send retries per signal
MIN_SOL_FOR_GAS   = 0.002 # minimum SOL balance to allow BUYs


def _wallet_usdc(wallet: dict) -> float:
    return next(
        (t["amount"] for t in wallet.get("tokens", []) if t["mint"] == USDC_MINT),
        0.0,
    )


def _refresh_usdc() -> float:
    """Single lightweight RPC call — just the USDC token balance."""
    token = get_token_balance(USDC_MINT)
    return token["amount"] if token else 0.0


def _preflight(wallet: dict, buy_signals: list, has_refill: bool = False) -> list:
    """
    Drop BUY signals that can't be funded right now.
    has_refill=True skips the raw SOL floor check because a REFILL signal
    will execute before any BUY and will top up SOL first.
    """
    if not has_refill and wallet.get("sol_balance", 0.0) < MIN_SOL_FOR_GAS:
        print(f"[Trade] PREFLIGHT: SOL critically low — dropping {len(buy_signals)} BUY(s)")
        return []

    usdc      = _wallet_usdc(wallet)
    total_buy = sum(s["amount"] for s in buy_signals)
    if total_buy > usdc:
        print(f"[Trade] PREFLIGHT: need ${total_buy:.4f} USDC, have ${usdc:.4f} — dropping BUYs")
        return []

    return buy_signals


def apply_shadow_fill(wallet: dict, signal: dict):
    """Update in-memory snapshot after a SELL so later trades see correct USDC."""
    if signal["type"] == "SELL":
        for t in wallet.get("tokens", []):
            if t["mint"] == signal["token_mint"]:
                t["amount"] = 0.0
                break


def execute_trades_batch(trade_signals: list) -> tuple[list, list]:
    """
    Execute a batch of trade signals in SELL-first order.

    After each confirmed SELL, compute the USDC gained and register it as a
    recycled slot so the next BUY cycle picks it up as one independent slot.

    Returns (successful_signals, failed_signals) — both lists contain the
    original signal dicts.  Only signals that confirmed on-chain are in
    successful_signals; everything else (pre-flight drops, retries exhausted,
    nothing queued) is in failed_signals.
    """
    refill_signals = [s for s in trade_signals if s["type"] == "REFILL"]
    sell_signals   = [s for s in trade_signals if s["type"] == "SELL"]
    buy_signals    = [s for s in trade_signals if s["type"] == "BUY"]

    wallet = get_wallet_state()
    save_wallet_db(wallet, 0.0)

    print(f"[Trade] Wallet: SOL={wallet.get('sol_balance', 0):.6f}  "
          f"USDC=${_wallet_usdc(wallet):.4f}  total=${wallet.get('total_usd', 0):.4f}")

    # REFILL being present means SOL will be topped up before BUYs execute —
    # pass that knowledge to preflight so it doesn't drop BUYs prematurely
    approved_buys = _preflight(wallet, buy_signals, has_refill=bool(refill_signals))
    dropped_buys  = [s for s in buy_signals if s not in approved_buys]

    # Execution order: REFILL (gas) -> SELL (free capital) -> BUY
    ordered_signals = refill_signals + sell_signals + approved_buys

    if not ordered_signals:
        print("[Trade] No executable signals after pre-flight")
        return [], list(trade_signals)

    successful_trades = []
    failed_trades     = list(dropped_buys)
    fees_accum_usd    = 0.0

    print(f"[Trade] Batch: {len(ordered_signals)} signals "
          f"({len(refill_signals)} REFILL, {len(sell_signals)} SELL, {len(approved_buys)} BUY)")

    for idx, original_signal in enumerate(ordered_signals, start=1):
        signal     = dict(original_signal)
        signal["_client_id"] = uuid4().hex
        sig_type   = signal["type"]
        is_sell    = sig_type == "SELL"
        is_refill  = sig_type == "REFILL"

        print(f"[Trade] {idx}/{len(ordered_signals)} "
              f"{sig_type} {signal['token_mint'][:12]}...")

        # Snapshot USDC before SELL to calculate delta afterwards
        usdc_before_sell = _wallet_usdc(wallet) if is_sell else 0.0

        attempt      = 0
        trade_done   = False
        final_status = None

        while attempt < MAX_ATTEMPTS and not trade_done:
            final_status = None
            try:
                # Always re-quote on each attempt — Jupiter blockhash expires ~60s
                tx     = handle_signal(signal, wallet)
                tx_sig = tx["signature"]
                print(f"[Trade] Attempt {attempt + 1} sent: {tx_sig}")

                for poll_idx in range(MAX_POLL_ATTEMPTS):
                    status  = check_trade_status(tx_sig)
                    if not status:
                        time.sleep(POLL_WAIT_TIME)
                        continue

                    success = status.get("success")
                    if success is True:
                        final_status = status
                        break
                    elif success is False:
                        raise RuntimeError(status.get("reason", "tx failed on-chain"))
                    else:
                        print(f"[Trade] Poll {poll_idx + 1}/{MAX_POLL_ATTEMPTS}: pending")
                        time.sleep(POLL_WAIT_TIME)

                if not final_status:
                    raise RuntimeError("tx not confirmed after polling window")

                # Fees
                fees_lamports   = final_status.get("fee_lamports") or 0
                sol_price_usd   = wallet["sol_usd"] / max(wallet["sol_balance"], 1e-9)
                fees_accum_usd += (fees_lamports / 1_000_000_000) * sol_price_usd

                # After SELL: capture USDC gained → recycled slot
                if is_sell:
                    usdc_after  = _refresh_usdc()
                    usdc_gained = usdc_after - usdc_before_sell
                    print(f"[Trade] SELL recovered ${usdc_after:.4f} USDC "
                          f"(gained ${usdc_gained:+.4f})")
                    if usdc_gained > 0:
                        register_recycled_slot(usdc_gained)
                    try:
                        from notify.reports import notify_trade_exit
                        notify_trade_exit(signal["token_mint"], usdc_after, usdc_gained)
                    except Exception:
                        pass
                    for t in wallet.get("tokens", []):
                        if t["mint"] == USDC_MINT:
                            t["amount"] = usdc_after
                            break

                # After REFILL: update in-memory SOL balance so fee calc stays accurate
                if is_refill:
                    from wallet.wallet_state import get_sol_balance
                    new_sol = get_sol_balance()
                    wallet["sol_balance"] = new_sol
                    print(f"[Trade] REFILL confirmed — SOL now {new_sol:.6f}")

                apply_shadow_fill(wallet, signal)
                trade_done = True
                print(f"[Trade] SUCCESS: {sig_type} {signal['token_mint'][:12]}...")

            except Exception as e:
                attempt += 1
                print(f"[Trade] Attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
                if attempt < MAX_ATTEMPTS:
                    time.sleep(POLL_WAIT_TIME)

        if trade_done:
            successful_trades.append(original_signal)
        else:
            print(f"[Trade] Giving up: {signal['type']} {signal['token_mint'][:12]}…")
            failed_trades.append(original_signal)

        time.sleep(TRADE_INTERVAL)

    try:
        wallet = get_wallet_state()
        save_wallet_db(wallet, fees_accum_usd)
    except Exception as e:
        print(f"[Trade] Final snapshot failed: {e}")

    print(f"[Trade] Batch done — "
          f"{len(successful_trades)} ok, {len(failed_trades)} failed, "
          f"fees ~${fees_accum_usd:.4f}")
    return successful_trades, failed_trades
