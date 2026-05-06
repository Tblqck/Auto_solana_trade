from trading.trade_orch_pipeline import execute_trades_batch


def run_trades(trade_signals: list) -> tuple[list, list]:
    """
    Execute a batch of trades and return (successful_trades, failed_trades).
    Each list contains simplified dicts with only 'type' and 'token_mint'.
    """
    successful, failed = execute_trades_batch(trade_signals)

    successful_simple = [{"type": t["type"], "token_mint": t["token_mint"]} for t in successful]
    failed_simple     = [{"type": t["type"], "token_mint": t["token_mint"]} for t in failed]

    return successful_simple, failed_simple
