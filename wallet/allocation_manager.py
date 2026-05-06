# allocation_manager.py
from datetime import datetime, timezone, timedelta

from core.db_utils import get_db_connection
from wallet.wallet_state import get_token_balance, get_sol_balance, get_token_price_usd

USDC_MINT          = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
NUM_SLOTS          = 5
DEFAULT_SLOT_HOURS = 24
SOL_RESERVE_USD    = 2.0
MIN_SLOT_USDC      = 1.0

PLANNED  = "planned"
RECYCLED = "recycled"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _live_trade_count() -> int:
    try:
        conn  = get_db_connection()
        cur   = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM live_trades")
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        print(f"[ALLOCATION] Could not read live_trades: {e}")
        return NUM_SLOTS  # fail-safe: block new buys


def _active_slots(now: datetime) -> list[dict]:
    """Return all non-expired slot rows from DB."""
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, slot_id, slot_type, start_timestamp, stop_timestamp, allocation_usd
            FROM allocation_slots
            WHERE stop_timestamp > ?
        """, (now.isoformat(),))
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "slot_id": r[1], "slot_type": r[2],
                "start_timestamp": r[3], "stop_timestamp": r[4],
                "allocation_usd": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[ALLOCATION] DB read error: {e}")
        return []


def _next_slot_id(slots: list[dict]) -> int:
    if not slots:
        return 1
    return max(s["slot_id"] for s in slots) + 1


# ── Public interface ──────────────────────────────────────────────────────────

def get_dynamic_allocation(hours: int = DEFAULT_SLOT_HOURS) -> float:
    now = datetime.now(timezone.utc)

    usdc_token   = get_token_balance(USDC_MINT)
    usdc_balance = usdc_token["amount"] if usdc_token else 0.0
    print(f"[ALLOCATION] USDC balance: ${usdc_balance:.4f}")
    if usdc_balance <= 0:
        print("[ALLOCATION] Zero USDC.")
        return 0.0

    sol_usd            = get_sol_balance() * get_token_price_usd("solana")
    sol_reserve_buffer = max(0.0, SOL_RESERVE_USD - sol_usd)
    if sol_reserve_buffer > 0:
        print(f"[ALLOCATION] SOL low (${sol_usd:.2f}) — reserving ${sol_reserve_buffer:.2f} USDC for gas")

    tradeable_usdc = max(0.0, usdc_balance - sol_reserve_buffer)
    if tradeable_usdc <= 0:
        print("[ALLOCATION] No tradeable USDC after SOL reserve.")
        return 0.0

    slots         = _active_slots(now)
    planned_slots = [s for s in slots if s["slot_type"] == PLANNED]
    planned_count = len(planned_slots)
    db_live       = _live_trade_count()
    used_slots    = max(planned_count, db_live)

    if used_slots >= NUM_SLOTS:
        print(f"[ALLOCATION] All {NUM_SLOTS} planned slots in use "
              f"(db_slots={planned_count}, db_live={db_live}).")
        return 0.0

    # If planned slots already exist this session, reuse their locked amount
    # so all 5 slots are equal. Only recalculate when starting fresh.
    if planned_slots:
        allocation_per_slot = planned_slots[0]["allocation_usd"]
        print(f"[ALLOCATION] Reusing session slot size -> ${allocation_per_slot:.4f}/slot"
              f"  (planned used: {used_slots}/{NUM_SLOTS})")
    else:
        allocation_per_slot = tradeable_usdc / NUM_SLOTS
        print(f"[ALLOCATION] ${tradeable_usdc:.4f} / {NUM_SLOTS} = "
              f"${allocation_per_slot:.4f}/slot  (planned used: {used_slots}/{NUM_SLOTS})")

    stop_ts = now + timedelta(hours=hours)
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO allocation_slots
                (slot_id, slot_type, start_timestamp, stop_timestamp, allocation_usd)
            VALUES (?, ?, ?, ?, ?)
        """, (
            _next_slot_id(slots), PLANNED,
            now.isoformat(), stop_ts.isoformat(),
            allocation_per_slot,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ALLOCATION] Failed to register planned slot: {e}")

    print(f"[ALLOCATION] Planned slot locked -> ${allocation_per_slot:.4f}")
    return allocation_per_slot


def register_recycled_slot(amount: float, hours: int = DEFAULT_SLOT_HOURS):
    if amount < MIN_SLOT_USDC:
        print(f"[ALLOCATION] Recycled amount ${amount:.4f} below minimum — not registering")
        return
    now     = datetime.now(timezone.utc)
    slots   = _active_slots(now)
    stop_ts = now + timedelta(hours=hours)
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO allocation_slots
                (slot_id, slot_type, start_timestamp, stop_timestamp, allocation_usd)
            VALUES (?, ?, ?, ?, ?)
        """, (
            _next_slot_id(slots), RECYCLED,
            now.isoformat(), stop_ts.isoformat(),
            amount,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ALLOCATION] Failed to register recycled slot: {e}")
        return
    print(f"[ALLOCATION] Recycled slot registered -> ${amount:.4f} "
          f"(expires {stop_ts.isoformat()})")
    try:
        from notify.reports import notify_recycled_slot
        notify_recycled_slot(amount)
    except Exception:
        pass


def claim_recycled_slot() -> float:
    now     = datetime.now(timezone.utc)
    slots   = _active_slots(now)
    recycled = sorted(
        [s for s in slots if s["slot_type"] == RECYCLED],
        key=lambda s: s["start_timestamp"],
    )
    if not recycled:
        return 0.0

    oldest = recycled[0]
    amount = float(oldest["allocation_usd"])
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("DELETE FROM allocation_slots WHERE id=?", (oldest["id"],))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ALLOCATION] Failed to claim recycled slot: {e}")
        return 0.0

    print(f"[ALLOCATION] Recycled slot {oldest['slot_id']} claimed -> ${amount:.4f}")
    return amount


if __name__ == "__main__":
    alloc = get_dynamic_allocation()
    print(f"\nPlanned allocation per trade: ${alloc:.4f}")
