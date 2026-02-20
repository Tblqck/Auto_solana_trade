from trade_orch_pipeline import execute_trades_batch

def run_trades(trade_signals):
    """
    Execute a batch of trades silently and return lists of successful and failed trades.

    Args:
        trade_signals (list): List of trade signals, e.g.
            [
                {"type": "BUY", "token_mint": "...", "amount": 1.0},
                {"type": "SELL", "token_mint": "..."}
            ]

    Returns:
        tuple: (successful_trades, failed_trades)
            Each is a list of dicts with keys: 'type' and 'token_mint'
    """

    # Execute trades (silent, no prints in this function)
    failed_trades = execute_trades_batch(trade_signals)

    # Determine successful trades
    successful_trades = [t for t in trade_signals if t not in failed_trades]

    # Simplify trades to only type & token_mint
    failed_trades_simple = [{"type": t["type"], "token_mint": t["token_mint"]} for t in failed_trades]
    successful_trades_simple = [{"type": t["type"], "token_mint": t["token_mint"]} for t in successful_trades]

    return successful_trades_simple, failed_trades_simple
