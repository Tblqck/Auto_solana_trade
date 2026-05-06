# trade_executor_run.py

from trading.trade_executor import run_trades
from trading.trade_2 import build_trade_signals

if __name__ == "__main__":
    # Get trade signals dynamically from trade_2.py
    trade_signals, _ = build_trade_signals()

    # Run trades
    successful, failed = run_trades(trade_signals)

    # Print only the summary
    print("✅ Successful trades:", successful)
    print("⚠️ Failed trades:", failed)
