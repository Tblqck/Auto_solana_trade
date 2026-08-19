# risk/circuit_breaker.py
"""
Engine-wide loss circuit breaker.

Tracks a trailing high-water mark of total wallet USD value. If the current
value drops DRAWDOWN_THRESHOLD below that peak, new BUY entries are halted
(existing open positions keep being managed normally by the stoploss
orchestrator/tightener). Trading resumes only via an explicit resume call
(cli.py resume, or the /resume Telegram command).
"""

from datetime import datetime, timezone

from core.db_utils import get_db_connection2

DRAWDOWN_THRESHOLD = 0.15  # 15% below peak trips the breaker


def _ensure_row(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM circuit_breaker_state WHERE id = 1")
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO circuit_breaker_state (id, peak_usd, halted) VALUES (1, 0, 0)"
        )
        conn.commit()


def is_buy_halted() -> bool:
    conn = get_db_connection2()
    try:
        _ensure_row(conn)
        cur = conn.cursor()
        cur.execute("SELECT halted FROM circuit_breaker_state WHERE id = 1")
        row = cur.fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def check_and_update(total_usd: float) -> bool:
    """
    Update the trailing peak and trip the breaker if drawdown exceeds
    DRAWDOWN_THRESHOLD. Returns True if the breaker is now halted
    (whether newly tripped this call or already halted).
    No-op on peak tracking once halted — resume_trading() resets the peak.
    """
    conn = get_db_connection2()
    try:
        _ensure_row(conn)
        cur = conn.cursor()
        cur.execute("SELECT peak_usd, halted FROM circuit_breaker_state WHERE id = 1")
        peak_usd, halted = cur.fetchone()

        if halted:
            return True

        new_peak = max(peak_usd, total_usd)
        drawdown = (new_peak - total_usd) / new_peak if new_peak > 0 else 0.0

        if drawdown >= DRAWDOWN_THRESHOLD:
            reason = (
                f"Drawdown {drawdown * 100:.1f}% "
                f"(peak ${new_peak:.2f} -> current ${total_usd:.2f})"
            )
            cur.execute(
                """
                UPDATE circuit_breaker_state
                SET peak_usd = ?, halted = 1, tripped_at = ?, tripped_reason = ?
                WHERE id = 1
                """,
                (new_peak, datetime.now(timezone.utc).isoformat(), reason),
            )
            conn.commit()
            print(f"[CircuitBreaker] TRIPPED — {reason}. New BUYs halted.")
            try:
                from notify.telegram import send as tg_send
                tg_send(
                    "<b>CIRCUIT BREAKER TRIPPED</b>\n\n"
                    f"{reason}\n\n"
                    "New BUY entries are halted. Existing positions continue "
                    "under normal stoploss management.\n"
                    "Send /resume (or run <code>python cli.py resume</code>) "
                    "to re-enable BUYs."
                )
            except Exception:
                pass
            return True

        cur.execute(
            "UPDATE circuit_breaker_state SET peak_usd = ? WHERE id = 1",
            (new_peak,),
        )
        conn.commit()
        return False
    finally:
        conn.close()


def resume_trading(current_total_usd: float) -> None:
    """Clear the halt and reset the trailing peak to the current wallet value."""
    conn = get_db_connection2()
    try:
        _ensure_row(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE circuit_breaker_state
            SET halted = 0, peak_usd = ?, tripped_at = NULL, tripped_reason = NULL
            WHERE id = 1
            """,
            (current_total_usd,),
        )
        conn.commit()
        print(f"[CircuitBreaker] Resumed — peak reset to ${current_total_usd:.2f}")
    finally:
        conn.close()


def get_status() -> dict:
    conn = get_db_connection2()
    try:
        _ensure_row(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT peak_usd, halted, tripped_at, tripped_reason FROM circuit_breaker_state WHERE id = 1"
        )
        peak_usd, halted, tripped_at, tripped_reason = cur.fetchone()
        return {
            "peak_usd": peak_usd,
            "halted": bool(halted),
            "tripped_at": tripped_at,
            "tripped_reason": tripped_reason,
        }
    finally:
        conn.close()
