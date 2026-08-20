import time
import threading
import contextlib
import io

from core.db_utils import get_db_connection
from signals.watcher_core import run_watcher_signal_based
from data.Data_Loop_core import run_data_loop

WATCHER_NAME            = "WATCHER"
SOL_AUTO_REFILL_USD     = 1.00   # auto-refill when SOL drops to this
SOL_REFILL_TARGET_USD   = 3.00   # top up to this level
SOL_CHECK_INTERVAL_S    = 60     # check SOL balance once per minute
SOL_REFILL_COOLDOWN_S   = 1800   # no more than one mid-window refill per 30 min

_last_sol_check_ts  = 0.0
_last_sol_refill_ts = 0.0


def is_module_on(module_name: str) -> bool:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM module_control WHERE module_name = ?", (module_name,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row[0].upper() == "ON"


def set_module_status(module_name: str, status: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control (module_name, status)
        VALUES (?, ?)
        ON CONFLICT(module_name) DO UPDATE SET status = excluded.status
    """, (module_name, status))
    conn.commit()
    conn.close()


def start_dataloop_background(interval_seconds=60, quiet=True):
    """Run DataLoop continuously in a background daemon thread."""
    def _loop():
        while True:
            try:
                if quiet:
                    with contextlib.redirect_stdout(io.StringIO()):
                        stats = run_data_loop()
                else:
                    print("[DataLoop] Background run triggered")
                    stats = run_data_loop()
                if stats:
                    try:
                        from notify.reports import accumulate_dataloop_stats
                        accumulate_dataloop_stats(
                            stats.get("pairs_checked", 0),
                            stats.get("rows_inserted", 0),
                        )
                    except Exception:
                        pass
            except Exception as e:
                print(f"[DataLoop] Background error: {e}")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    print(f"[Watcher] DataLoop background thread started (every {interval_seconds}s, quiet={quiet})")


def start_pair_discovery_background(interval_seconds=7200, quiet=True):
    """Run new-token discovery (data/get_pairs.py) continuously in its own
    background daemon thread. Metadata-only writes (tokens/supported_tokens)
    — never touches trade_risk_state/live_trades, so it can't disrupt open
    positions or a currently-running signal/trade cycle."""
    def _loop():
        while True:
            try:
                from data.get_pairs import run_all as run_discovery
                if quiet:
                    with contextlib.redirect_stdout(io.StringIO()):
                        stats = run_discovery()
                else:
                    print("[Discovery] Run triggered")
                    stats = run_discovery()
                if stats:
                    print(f"[Discovery] {stats.get('candidates', 0)} candidates, "
                          f"{stats.get('supported', 0)} tradable on Jupiter")
            except Exception as e:
                print(f"[Discovery] Background error: {e}")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True, name="pair-discovery")
    thread.start()
    print(f"[Watcher] Pair discovery background thread started (every {interval_seconds}s)")


def _check_sol_balance():
    """
    Check SOL USD value every SOL_CHECK_INTERVAL_S seconds.
    If SOL drops to SOL_AUTO_REFILL_USD ($1.00) or below, automatically
    execute a mid-window USDC -> SOL refill (capped to SOL_REFILL_COOLDOWN_S).
    Startup refill (main.py) is unaffected — this is the mid-window safety net.
    """
    global _last_sol_check_ts, _last_sol_refill_ts
    now = time.time()

    if now - _last_sol_check_ts < SOL_CHECK_INTERVAL_S:
        return
    _last_sol_check_ts = now

    try:
        from wallet.wallet_state import get_sol_balance, get_token_price_usd
        sol_balance = get_sol_balance()
        sol_price   = get_token_price_usd("solana")
        sol_usd     = sol_balance * sol_price

        if sol_usd > SOL_AUTO_REFILL_USD:
            return
        if now - _last_sol_refill_ts < SOL_REFILL_COOLDOWN_S:
            return

        needed_usd = SOL_REFILL_TARGET_USD - sol_usd
        if needed_usd <= 0:
            return

        print(f"[Watcher] SOL ${sol_usd:.2f} <= ${SOL_AUTO_REFILL_USD:.2f} — mid-window refill ${needed_usd:.2f}")
        from trading.trade_engine import execute_swap
        _SOL_MINT  = "So11111111111111111111111111111111111111112"
        _USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        result = execute_swap(
            input_mint=_USDC_MINT,
            output_mint=_SOL_MINT,
            amount_ui=needed_usd,
            input_decimals=6,
            slippage_bps=50,
        )
        print(f"[Watcher] Mid-window refill tx: {result['signature']}")
        _last_sol_refill_ts = now

        try:
            from wallet.allocation_manager import deduct_refill_from_slots
            deduct_refill_from_slots(needed_usd)
        except Exception:
            pass

        try:
            from notify.reports import notify_sol_low
            notify_sol_low(sol_usd)
        except Exception:
            pass

    except Exception as e:
        print(f"[Watcher] SOL refill failed: {e}")


def watcher(interval=30):
    print("[Watcher] Started")
    set_module_status(WATCHER_NAME, "ON")
    start_dataloop_background(interval_seconds=60, quiet=True)
    start_pair_discovery_background(interval_seconds=7200, quiet=True)

    _REPORT_INTERVAL = 3600  # 1 hour
    last_report_ts   = time.time()

    try:
        while True:
            if not is_module_on(WATCHER_NAME):
                print("[Watcher] Disabled from DB — stopping")
                break

            run_watcher_signal_based()
            _check_sol_balance()

            # Fire hourly reports
            if time.time() - last_report_ts >= _REPORT_INTERVAL:
                try:
                    from notify.reports import (
                        send_hourly_wallet_report,
                        send_hourly_dataloop_report,
                    )
                    send_hourly_wallet_report()
                    send_hourly_dataloop_report()
                except Exception as e:
                    print(f"[Watcher] Hourly report error: {e}")
                last_report_ts = time.time()

            print(f"[Watcher] Sleeping {interval}s before next cycle")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("[Watcher] Interrupted by user")

    finally:
        set_module_status(WATCHER_NAME, "OFF")
        print("[Watcher] Stopped safely")


if __name__ == "__main__":
    watcher(interval=10)
