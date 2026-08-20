"""
notify/commands.py

Telegram command listener (long-polling). Runs as the sole listener inside
scripts/telegram_supervisor.py — an always-on process separate from
main.py, so /startengine still works even when the trading engine itself
is fully stopped. (main.py used to run its own listener; don't add that
back — two processes long-polling the same bot's getUpdates steal each
other's updates.)

Handles:
    /help        — this list
    /state       — wallet balances + open positions
    /pnl         — P&L since session start + top contributing tokens
    /liquidate   — sells all token positions via liquidate_all()
    /resume      — clears the circuit breaker halt and resumes BUYs
    /startengine — launches main.py if it isn't running
    /shutdown    — gracefully stops main.py if it is running
"""

import io
import os
import signal
import subprocess
import time
import threading
import contextlib
from pathlib import Path

import requests

from notify.telegram import _BOT_TOKEN, _CHAT_ID, send

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_PROJECT_DIR = Path(__file__).resolve().parents[1]


def _get_updates(offset: int) -> list[dict]:
    if not _BOT_TOKEN:
        return []
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 30},
            timeout=35,
        )
        if resp.ok:
            return resp.json().get("result", [])
    except Exception:
        pass
    return []


# ── Command handlers ───────────────────────────────────────────────────────────

def _handle_liquidate() -> str:
    send("<b>Liquidate</b>\n\nStarting liquidation of all positions...")
    try:
        from trading.liquidate import liquidate_all
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            liquidate_all()
        output = buf.getvalue().strip()
        return f"<b>Liquidate — Done</b>\n\n<pre>{output or 'No output.'}</pre>"
    except Exception as e:
        return f"<b>Liquidate — ERROR</b>\n\n{e}"


def _handle_resume() -> str:
    try:
        from wallet.wallet_state import get_wallet_state
        from risk.circuit_breaker import get_status, resume_trading

        status = get_status()
        if not status["halted"]:
            return "<b>Resume</b>\n\nCircuit breaker is not halted — nothing to resume."

        total_usd = get_wallet_state().get("total_usd", 0.0)
        resume_trading(total_usd)
        return (
            "<b>Resume — Done</b>\n\n"
            f"Was halted: {status['tripped_reason']}\n"
            f"New peak baseline: ${total_usd:.2f}\n"
            "BUYs re-enabled."
        )
    except Exception as e:
        return f"<b>Resume — ERROR</b>\n\n{e}"


def _handle_state() -> str:
    try:
        from wallet.wallet_state import get_wallet_state
        from risk.circuit_breaker import get_status
        w = get_wallet_state()
        breaker = get_status()

        sol_bal = w.get("sol_balance", 0.0)
        sol_usd = w.get("sol_usd", 0.0)
        total   = w.get("total_usd", 0.0)
        tokens  = w.get("tokens", [])

        usdc   = next((t["amount"] for t in tokens if t["mint"] == USDC_MINT), 0.0)
        others = [t for t in tokens if t["mint"] != USDC_MINT]

        lines = ["<b>Wallet State</b>\n"]
        if breaker["halted"]:
            lines.append(f"⛔ CIRCUIT BREAKER HALTED: {breaker['tripped_reason']}")
            lines.append("Send /resume to re-enable BUYs.\n")
        lines += [
            f"SOL:   {sol_bal:.4f} SOL  (~${sol_usd:.2f})",
            f"USDC:  ${usdc:.2f}",
            f"Total: ${total:.2f}",
        ]

        if others:
            lines.append(f"\n<b>Positions ({len(others)})</b>")
            for t in others:
                short   = t["mint"][:16] + "..."
                usd_val = t.get("usd_value")
                usd_str = f"${usd_val:.4f}" if usd_val is not None else "no price"
                lines.append(f"  {short}  {t['amount']:.4f}  |  {usd_str}")
        else:
            lines.append("\nNo token positions held.")

        return "\n".join(lines)
    except Exception as e:
        return f"<b>Wallet State — ERROR</b>\n\n{e}"


def _handle_pnl() -> str:
    try:
        from wallet.wallet_state import get_wallet_state
        from core.db_utils import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT started_at, start_usd FROM session_baseline WHERE id=1")
        row = cur.fetchone()

        current_total = get_wallet_state().get("total_usd", 0.0)

        lines = ["<b>Session P&amp;L</b>\n"]
        started_at = None
        if row:
            started_at, start_usd = row
            delta = current_total - start_usd
            pct = (delta / start_usd * 100) if start_usd > 0 else 0.0
            sign = "+" if delta >= 0 else ""
            lines.append(f"Started: {started_at[:16].replace('T', ' ')} UTC")
            lines.append(f"Start:   ${start_usd:.2f}")
            lines.append(f"Now:     ${current_total:.2f}")
            lines.append(f"P&amp;L:     {sign}${delta:.2f}  ({sign}{pct:.2f}%)")
        else:
            lines.append("No session baseline recorded yet — engine hasn't completed a startup.")

        top = []
        if started_at:
            cur.execute("""
                SELECT COALESCE(symbol, contract) AS label, SUM(realized_pnl) AS total_pnl, COUNT(*) AS trades
                FROM trade_pnl_log
                WHERE closed_at >= ?
                GROUP BY contract
                ORDER BY total_pnl DESC
                LIMIT 5
            """, (started_at,))
            top = cur.fetchall()
        conn.close()

        if top:
            lines.append("\n<b>Top contributors this session</b>")
            for label, total_pnl, trades in top:
                sign2 = "+" if total_pnl >= 0 else ""
                lines.append(f"  {label}: {sign2}${total_pnl:.2f} ({trades} trade{'s' if trades != 1 else ''})")
        else:
            lines.append("\nNo closed trades yet this session.")

        return "\n".join(lines)
    except Exception as e:
        return f"<b>P&amp;L — ERROR</b>\n\n{e}"


def _find_main_pid() -> int | None:
    """ps-based lookup (not pgrep — not guaranteed installed) for a running
    `python main.py` process."""
    try:
        out = subprocess.check_output(["ps", "-eo", "pid,args"]).decode()
        for line in out.splitlines():
            if "python main.py" in line and "grep" not in line:
                return int(line.strip().split()[0])
    except Exception:
        pass
    return None


def _handle_startengine() -> str:
    pid = _find_main_pid()
    if pid:
        return f"<b>Start Engine</b>\n\nAlready running (pid {pid})."
    try:
        log_dir = _PROJECT_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = open(log_dir / "engine.log", "a")
        proc = subprocess.Popen(
            ["python", "main.py"],
            cwd=str(_PROJECT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return f"<b>Start Engine — Done</b>\n\nLaunched (pid {proc.pid}). Logs: logs/engine.log"
    except Exception as e:
        return f"<b>Start Engine — ERROR</b>\n\n{e}"


def _handle_shutdown() -> str:
    pid = _find_main_pid()
    if not pid:
        return "<b>Shutdown</b>\n\nEngine is not running."
    try:
        os.kill(pid, signal.SIGINT)
        return f"<b>Shutdown</b>\n\nSent graceful stop signal to engine (pid {pid}). It will finish its shutdown shortly."
    except Exception as e:
        return f"<b>Shutdown — ERROR</b>\n\n{e}"


def _handle_help() -> str:
    return (
        "<b>sol_trade — Commands</b>\n\n"
        "/state — wallet balances + open positions\n"
        "/pnl — P&amp;L since session start + top contributing tokens\n"
        "/liquidate — sell every open position now\n"
        "/resume — clear a tripped circuit breaker, re-enable BUYs\n"
        "/startengine — launch the trading engine if it's stopped\n"
        "/shutdown — gracefully stop the trading engine\n"
        "/help — this message"
    )


# ── Dispatch ───────────────────────────────────────────────────────────────────

_COMMANDS = {
    "/liquidate":   _handle_liquidate,
    "/state":       _handle_state,
    "/resume":      _handle_resume,
    "/pnl":         _handle_pnl,
    "/startengine": _handle_startengine,
    "/shutdown":    _handle_shutdown,
    "/help":        _handle_help,
}


def _dispatch(text: str) -> str | None:
    cmd = text.strip().lower().split()[0] if text.strip() else ""
    handler = _COMMANDS.get(cmd)
    return handler() if handler else None


# ── Polling loop ───────────────────────────────────────────────────────────────

def _poll_loop():
    offset = 0
    print("[Commands] Telegram command listener running.")
    while True:
        try:
            updates = _get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                msg     = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text    = msg.get("text", "")
                if chat_id != _CHAT_ID or not text:
                    continue
                reply = _dispatch(text)
                if reply:
                    send(reply)
        except Exception as e:
            print(f"[Commands] Poll error: {e}")
            time.sleep(5)


def start_command_listener() -> threading.Thread:
    t = threading.Thread(target=_poll_loop, daemon=True, name="tg-commands")
    t.start()
    return t
