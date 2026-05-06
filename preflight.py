"""
preflight.py — Pre-deployment validation.

Run standalone:   python preflight.py
Called by main:   from preflight import run_preflight; run_preflight()

CRITICAL failures abort startup (exit 1).
WARNings allow startup but flag degraded capability.
"""
import os
import sys
import sqlite3

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

# ── Result accumulator ───────────────────────────────────────────────────────
_results: list[tuple[str, str]] = []


def _ok(label: str, detail: str = ""):
    _results.append(("ok", label))
    suffix = f" | {detail}" if detail else ""
    print(f"  [  OK  ] {label}{suffix}")


def _warn(label: str, detail: str = ""):
    _results.append(("warn", label))
    suffix = f" | {detail}" if detail else ""
    print(f"  [ WARN ] {label}{suffix}")


def _fail(label: str, detail: str = ""):
    _results.append(("fail", label))
    suffix = f" | {detail}" if detail else ""
    print(f"  [ FAIL ] {label}{suffix}")


# ── Constants ────────────────────────────────────────────────────────────────
REQUIRED_ENV = {
    "PRIVATE_KEY": "Solana wallet private key (base58) — required to sign txs",
    "ALCHEMY_RPC": "Alchemy RPC URL — required for tx confirmation polling",
}

REQUIRED_TABLES = [
    "tokens",
    "supported_tokens",
    "ohlc_data",
    "ai_thought",
    "pending_trades",
    "live_trades",
    "trade_risk_state",
    "loss_guard_log",
    "module_control",
    "module_status",
]

USDC_MINT      = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_RESERVE_USD = 2.0


# ── Check functions ──────────────────────────────────────────────────────────

def check_env():
    print("\n[1/5] Environment variables")
    for key, desc in REQUIRED_ENV.items():
        val = os.getenv(key)
        if val:
            _ok(key, f"{len(val)} chars")
        else:
            _fail(key, desc)


def check_config() -> dict | None:
    print("\n[2/5] Config + models")

    if not os.path.exists("config.yaml"):
        _fail("config.yaml", "file not found — cannot determine DB path")
        return None

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    _ok("config.yaml")

    db_path = cfg.get("DB_PATH")
    if db_path:
        _ok("DB_PATH", db_path)
    else:
        _fail("DB_PATH", "key missing from config.yaml")

    for key in ("classifier_model", "regressor_model"):
        path = cfg.get(key)
        if not path:
            _warn(key, "not configured — AI pipeline will fail")
        elif os.path.exists(path):
            _ok(key, path)
        else:
            _warn(key, f"'{path}' not found — AI pipeline will fail")

    return cfg


def check_db(cfg: dict | None):
    print("\n[3/5] Database")

    if not cfg:
        _fail("DB", "skipped — config not loaded")
        return

    db_path = cfg.get("DB_PATH", "")
    if not os.path.exists(db_path):
        _fail("DB file", f"'{db_path}' not found — run db_creator.py to initialise")
        return
    _ok("DB file", db_path)

    try:
        conn     = sqlite3.connect(db_path)
        cur      = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {r[0] for r in cur.fetchall()}
        conn.close()

        missing = [t for t in REQUIRED_TABLES if t not in existing]
        if missing:
            _fail("Required tables", f"missing: {', '.join(missing)} — run db_creator.py")
        else:
            _ok("Required tables", f"all {len(REQUIRED_TABLES)} present")

    except Exception as e:
        _fail("DB connect", str(e))


def check_rpc():
    print("\n[4/5] External connectivity")

    # Alchemy
    alchemy_url = os.getenv("ALCHEMY_RPC")
    if alchemy_url:
        try:
            resp = requests.post(
                alchemy_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "getHealth"},
                timeout=8,
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("result") == "ok":
                _ok("Alchemy RPC", "healthy")
            else:
                _warn("Alchemy RPC", f"responded but unexpected body: {str(data)[:80]}")
        except Exception as e:
            _fail("Alchemy RPC", f"unreachable — {e}")
    else:
        _fail("Alchemy RPC", "env var not set")

    # Jupiter — do a real micro-quote so we know routing works
    try:
        resp = requests.get(
            "https://lite-api.jup.ag/swap/v1/quote",
            params={
                "inputMint":   USDC_MINT,
                "outputMint":  "So11111111111111111111111111111111111111112",  # SOL
                "amount":      1_000_000,  # $1 USDC
                "slippageBps": 50,
            },
            timeout=8,
        )
        if "routePlan" in resp.json():
            _ok("Jupiter API", "quote endpoint live")
        else:
            _warn("Jupiter API", f"unexpected response: {resp.text[:80]}")
    except Exception as e:
        _fail("Jupiter API", f"unreachable — {e}")


def check_wallet():
    print("\n[5/5] Wallet state")

    if not os.getenv("PRIVATE_KEY"):
        _warn("Wallet", "PRIVATE_KEY not set — skipping on-chain checks")
        return

    try:
        from wallet.wallet_state import get_sol_balance, get_token_balance, get_token_price_usd

        sol_balance = get_sol_balance()
        sol_price   = get_token_price_usd("solana")
        sol_usd     = sol_balance * sol_price

        if sol_usd >= SOL_RESERVE_USD:
            _ok("SOL balance", f"{sol_balance:.6f} SOL (~${sol_usd:.2f})")
        else:
            _warn(
                "SOL balance",
                f"{sol_balance:.6f} SOL (~${sol_usd:.2f}) "
                f"below ${SOL_RESERVE_USD:.2f} reserve | "
                f"auto-REFILL will swap USDC -> SOL on first trade cycle",
            )

        usdc_token  = get_token_balance(USDC_MINT)
        usdc_amount = usdc_token["amount"] if usdc_token else 0.0

        if usdc_amount > 0:
            _ok("USDC balance", f"${usdc_amount:.4f} available to trade")
        else:
            _warn("USDC balance", "$0.00 — no BUYs will execute until funded")

    except Exception as e:
        _warn("Wallet check", f"RPC call failed — {e}")


# ── Entry point ──────────────────────────────────────────────────────────────

def run_preflight(hard_fail: bool = True) -> bool:
    """
    Run all checks and print a summary.

    hard_fail=True  → sys.exit(1) on any CRITICAL failure (used by main.py).
    hard_fail=False → return False on failure (useful for tests/CI).
    """
    _results.clear()

    print("=" * 58)
    print("  SOL TRADE — PRE-DEPLOYMENT CHECK")
    print("=" * 58)

    cfg = check_config()
    check_env()
    check_db(cfg)
    check_rpc()
    check_wallet()

    fails = [label for status, label in _results if status == "fail"]
    warns = [label for status, label in _results if status == "warn"]

    print("\n" + "=" * 58)
    if fails:
        print(f"  RESULT: {len(fails)} CRITICAL failure(s),  {len(warns)} warning(s)\n")
        for label in fails:
            print(f"    FAIL  {label}")
        print()
        if hard_fail:
            print("  Fix critical issues before deploying.  Aborting.")
            print("=" * 58)
            sys.exit(1)
        return False

    if warns:
        print(f"  RESULT: PASS  ({len(warns)} warning(s) - see above)\n")
        for label in warns:
            print(f"    WARN  {label}")
    else:
        print("  RESULT: ALL CHECKS PASSED")

    print("=" * 58 + "\n")
    return True


if __name__ == "__main__":
    run_preflight(hard_fail=True)
