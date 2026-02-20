import time
from trade_shadow import handle_signal

def execute_trades_batch(trade_signals: list, retry_attempts: int = 3, retry_delay: float = 3.0, trade_delay: float = 3.0):
    """
    Executes a list of trade signals sequentially, ensuring full token clearance on SELL.
    Retries failed trades up to `retry_attempts` times on RPC 429 errors.
    
    trade_signals = [
        {"type": "BUY"|"SELL", "token_mint": "<mint>", "amount": <float, if BUY>, "slippage_bps": 50},
        ...
    ]

    trade_delay: seconds to wait between trades (default 3s)
    """
    results = []
    failed_trades = []

    print(f"🔹 Starting batch execution: {len(trade_signals)} trades\n")

    for i, signal in enumerate(trade_signals, start=1):
        print(f"🔸 Processing trade {i}/{len(trade_signals)} → {signal['type']} {signal.get('amount', 'ALL')} {signal['token_mint']}")

        attempt = 0
        success = False

        while attempt < retry_attempts and not success:
            try:
                # Call shadow to execute the trade
                result = handle_signal(signal)
                results.append(result)

                if result["success"]:
                    print(f"✅ Trade success: {signal['token_mint']}")
                    success = True
                else:
                    reason = str(result["reason"])
                    print(f"❌ Trade failed: {signal['token_mint']} Reason: {reason}")

                    # Retry if RPC rate limit
                    if "Too many requests" in reason or "429" in reason:
                        attempt += 1
                        print(f"🔁 RPC rate-limit hit. Retrying in {retry_delay}s... (Attempt {attempt}/{retry_attempts})")
                        time.sleep(retry_delay)
                    else:
                        failed_trades.append(signal)
                        success = True  # stop retrying for other errors

            except Exception as e:
                err_str = str(e)
                print(f"⚠️ Trade error: {signal['token_mint']} → {err_str}")
                if "429" in err_str:
                    attempt += 1
                    print(f"🔁 RPC rate-limit hit. Retrying in {retry_delay}s... (Attempt {attempt}/{retry_attempts})")
                    time.sleep(retry_delay)
                else:
                    failed_trades.append(signal)
                    success = True

        # Wait trade_delay seconds before next trade
        time.sleep(trade_delay)

    # -----------------------------
    # Log failed trades
    # -----------------------------
    if failed_trades:
        print("\n⚠️ Some trades failed after retries:")
        for f in failed_trades:
            print(f"⏹ Failed trade: {f}")

    print("\n🔹 Batch execution complete")
    return results, failed_trades
