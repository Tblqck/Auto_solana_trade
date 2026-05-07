# main.py
import os
import time
import sqlite3
import subprocess
import threading
import yaml

SOL_STARTUP_TARGET_USD = 3.00
_SOL_SWAP_MIN_USD      = 0.10
_SOL_MINT  = "So11111111111111111111111111111111111111112"
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _get_db_path():
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    return config["DB_PATH"]


def ensure_db_schema():
    """Create any missing tables without touching existing data."""
    from core.db_schema.db_creator import init_db
    init_db()
    print("[Main] DB schema verified.")


def reset_module_control():
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    for module in ("AI_BOT", "WATCHER", "DataLoop", "trade_engine", "sol_refill_done"):
        cur.execute("""
            INSERT INTO module_control (module_name, status)
            VALUES (?, 'OFF')
            ON CONFLICT(module_name) DO UPDATE SET status='OFF'
        """, (module,))
    conn.commit()
    conn.close()
    print("[Main] Module control reset: all OFF.")


def _mark_sol_refill_done():
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO module_control (module_name, status)
        VALUES ('sol_refill_done', 'ON')
        ON CONFLICT(module_name) DO UPDATE SET status='ON'
    """)
    conn.commit()
    conn.close()


def rebalance_sol_at_startup():
    from wallet.wallet_state import get_sol_balance, get_token_price_usd
    from trading.trade_engine import execute_swap

    sol_balance = get_sol_balance()
    sol_price   = get_token_price_usd("solana")
    sol_usd     = sol_balance * sol_price

    print(f"[Startup] SOL balance: {sol_balance:.6f} SOL (~${sol_usd:.2f})")

    if sol_usd > SOL_STARTUP_TARGET_USD + _SOL_SWAP_MIN_USD:
        excess_usd = sol_usd - SOL_STARTUP_TARGET_USD
        excess_sol = excess_usd / sol_price
        print(f"[Startup] SOL ${sol_usd:.2f} above ${SOL_STARTUP_TARGET_USD:.2f} target "
              f"-> selling {excess_sol:.6f} SOL (${excess_usd:.2f}) back to USDC")
        try:
            result = execute_swap(
                input_mint=_SOL_MINT,
                output_mint=_USDC_MINT,
                amount_ui=excess_sol,
                input_decimals=9,
                slippage_bps=50,
            )
            print(f"[Startup] SOL -> USDC rebalance tx: {result['signature']}")
        except Exception as e:
            print(f"[Startup] SOL rebalance failed (non-fatal): {e}")

    elif sol_usd < SOL_STARTUP_TARGET_USD:
        needed_usd = SOL_STARTUP_TARGET_USD - sol_usd
        print(f"[Startup] SOL ${sol_usd:.2f} below ${SOL_STARTUP_TARGET_USD:.2f} "
              f"-> buying ${needed_usd:.2f} of SOL (one-time startup refill)")
        try:
            result = execute_swap(
                input_mint=_USDC_MINT,
                output_mint=_SOL_MINT,
                amount_ui=needed_usd,
                input_decimals=6,
                slippage_bps=50,
            )
            print(f"[Startup] USDC -> SOL refill tx: {result['signature']}")
        except Exception as e:
            print(f"[Startup] SOL refill failed (non-fatal): {e}")

    else:
        print(f"[Startup] SOL ${sol_usd:.2f} within target range, no rebalance needed")

    # Mark startup refill as done — prevents mid-window auto-refill
    _mark_sol_refill_done()


def start_hourly_reports(stop_event: threading.Event):
    """Background thread: sends hourly DataLoop digest + wallet report."""
    def _run():
        while not stop_event.wait(timeout=3600):
            try:
                from notify.reports import send_hourly_dataloop_report, send_hourly_wallet_report
                send_hourly_dataloop_report()
                send_hourly_wallet_report()
            except Exception as e:
                print(f"[Notify] Hourly report error (non-fatal): {e}")
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def wait_for_dataloop_ready(timeout=120):
    db_path = _get_db_path()
    start = time.time()
    while time.time() - start < timeout:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT last_run FROM module_status WHERE module_name='DataLoop'"
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                print("[Main] DataLoop ready. Proceeding...")
                return True
        except Exception as e:
            print(f"[Main] DB check error: {e}")
        print("[Main] Waiting for DataLoop first run...")
        time.sleep(5)
    return False


if __name__ == "__main__":
    from preflight import run_preflight
    run_preflight(hard_fail=True)

    ensure_db_schema()
    reset_module_control()
    rebalance_sol_at_startup()

    try:
        from notify.telegram import send as tg_send
        tg_send("<b>sol_trade started</b>\nPreflight passed. System initialising...")
    except Exception:
        pass

    stop_reports = threading.Event()
    start_hourly_reports(stop_reports)
    print("[Main] Hourly report thread started.")

    watcher_proc = subprocess.Popen(["python", "-m", "signals.watcher"])
    print("[Main] Watcher started.")

    if not wait_for_dataloop_ready():
        print("[Main] DataLoop did not complete first run in time. Aborting.")
        watcher_proc.terminate()
        stop_reports.set()
        exit(1)

    print("[Main] System running for 12 hours...")
    time.sleep(12 * 3600)

    print("[Main] 12 hours reached. Shutting down...")
    watcher_proc.terminate()
    stop_reports.set()

    try:
        from notify.telegram import send as tg_send
        tg_send("<b>sol_trade session ended</b>\n12-hour window complete. Goodbye.")
    except Exception:
        pass

    print("[Main] System shut down.")
