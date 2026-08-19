"""
notify/commands.py

Telegram command listener (long-polling).
Handles:
    /liquidate  — sells all token positions via liquidate_all()
    /state      — returns a formatted wallet state summary
    /resume     — clears the circuit breaker halt and resumes BUYs
"""

import io
import time
import threading
import contextlib
import requests

from notify.telegram import _BOT_TOKEN, _CHAT_ID, send

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


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


# ── Dispatch ───────────────────────────────────────────────────────────────────

_COMMANDS = {
    "/liquidate": _handle_liquidate,
    "/state":     _handle_state,
    "/resume":    _handle_resume,
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
