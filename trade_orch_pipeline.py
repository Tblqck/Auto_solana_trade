import time
from uuid import uuid4

from trade_shadow import handle_signal
from wallet_state import get_wallet_state, save_wallet_csv
from trade_tracker import check_trade_status

TRADE_INTERVAL = 3
MAX_POLL_ATTEMPTS = 15
POLL_WAIT_TIME = 2


def apply_shadow_fill(wallet: dict, signal: dict):
    """
    Update in-memory wallet snapshot after a successful trade.
    (SELL logic sets token amount to 0)
    """
    if signal["type"] == "SELL":
        for t in wallet.get("tokens", []):
            if t["mint"] == signal["token_mint"]:
                t["amount"] = 0.0
                break


def execute_trades_batch(trade_signals: list):
    """
    Execute a batch of trade signals.

    Returns:
        failed_trades = [original_signal]
    """

    # ---------------------------
    # SELL first
    # ---------------------------
    sell_signals = [s for s in trade_signals if s["type"] == "SELL"]
    buy_signals = [s for s in trade_signals if s["type"] == "BUY"]
    ordered_signals = sell_signals + buy_signals

    failed_trades = []
    fees_accum_usd = 0.0

    print(f"🔹 Starting batch execution: {len(ordered_signals)} trades")

    # ---------------------------
    # snapshot wallet ONCE
    # ---------------------------
    wallet = get_wallet_state()
    save_wallet_csv(wallet, fees_accum_usd)

    for idx, original_signal in enumerate(ordered_signals, start=1):

        signal = dict(original_signal)
        signal["_client_id"] = uuid4().hex

        print(
            f"\n🔸 Trade {idx}/{len(ordered_signals)} "
            f"{signal['type']} {signal['token_mint']} "
            f"(cid={signal['_client_id']})"
        )

        attempt = 0
        max_attempts = 3
        sent = False
        trade_done = False
        tx_sig = None
        final_status = None

        while attempt < max_attempts and not trade_done:

            try:
                # ---------------------------
                # Send trade ONLY once
                # ---------------------------
                if not sent:
                    tx = handle_signal(signal, wallet)
                    tx_sig = tx["signature"]
                    sent = True
                    print(f"📤 Trade sent: {tx_sig}")

                # ---------------------------
                # Poll confirmation
                # ---------------------------
                for poll_idx in range(MAX_POLL_ATTEMPTS):

                    status = check_trade_status(tx_sig)

                    if not status:
                        print(f"⚠️ Poll {poll_idx+1}: no status returned")
                        time.sleep(POLL_WAIT_TIME)
                        continue

                    if status.get("reason") == "Transaction not found or not confirmed yet":
                        print(f"⚠️ Poll {poll_idx+1}: still pending")
                        time.sleep(POLL_WAIT_TIME)
                        continue

                    final_status = status
                    break

                if not final_status:
                    raise RuntimeError("No final status returned after polling")

                if final_status.get("success") is False:
                    raise RuntimeError(final_status.get("reason"))

                # ---------------------------
                # SUCCESS
                # ---------------------------
                print(f"✅ Trade SUCCESS: {signal['type']} {signal['token_mint']}")

                fees_lamports = final_status.get("fee_lamports") or 0
                sol_price = wallet["sol_usd"] / max(wallet["sol_balance"], 1e-9)
                fees_usd = (fees_lamports / 1_000_000_000) * sol_price
                fees_accum_usd += fees_usd

                apply_shadow_fill(wallet, signal)
                trade_done = True

            except Exception as e:
                print(f"⚠️ Trade confirmation error: {e}")
                attempt += 1
                time.sleep(POLL_WAIT_TIME)

        if not trade_done:
            print(f"⏹ Failed trade after {max_attempts} attempts: {original_signal}")
            failed_trades.append(original_signal)

        time.sleep(TRADE_INTERVAL)

    # ---------------------------
    # Refresh wallet after batch
    # ---------------------------
    try:
        wallet = get_wallet_state()
        save_wallet_csv(wallet, fees_accum_usd)
    except Exception as e:
        print(f"⚠️ Failed to refresh wallet after batch: {e}")

    print("\n🔹 Batch execution complete")

    return failed_trades


# ----------------------
# Example usage
# ----------------------
if __name__ == "__main__":
    trade_signals = [
       #{"type": "BUY", "token_mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "amount": 1.0},
       #"type": "BUY", "token_mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "amount": 2.0},
       {"type": "SELL", "token_mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}
    ]

    failed = execute_trades_batch(trade_signals)

    print("\n⚠️ Failed trades:", failed)
