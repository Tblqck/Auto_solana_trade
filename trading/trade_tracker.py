# trade_tracker.py
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

RPC_URL = os.getenv("ALCHEMY_RPC")
if not RPC_URL:
    raise ValueError("ALCHEMY_RPC not set in .env")

MAX_RETRIES  = 3
RETRY_DELAY  = 1


def check_trade_status(tx_sig: str) -> dict:
    """
    Poll for transaction confirmation via Alchemy RPC.
    Returns:
        {"success": True,  "reason": None,   "fee_lamports": int}   — confirmed ok
        {"success": False, "reason": str,    "fee_lamports": int}   — confirmed failed
        {"success": None,  "reason": str,    "fee_lamports": None}  — still pending / rpc error
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_sig,
            {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0},
        ],
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(RPC_URL, json=payload, timeout=10).json()

            if "error" in resp:
                code = resp["error"].get("code")
                msg  = resp["error"].get("message", "")
                if code == 429 or "Too many requests" in msg:
                    print(f"[Tracker] Rate limited, retry {attempt + 1}/{MAX_RETRIES}")
                    time.sleep(RETRY_DELAY * (2 ** attempt))
                    continue
                return {"success": False, "reason": f"RPC error: {resp['error']}", "fee_lamports": None}

            result = resp.get("result")
            if not result:
                return {"success": None, "reason": "not confirmed yet", "fee_lamports": None}

            meta  = result.get("meta", {})
            fee   = meta.get("fee", 0)
            error = meta.get("err")

            if error is None:
                return {"success": True, "reason": None, "fee_lamports": fee}

            # tx landed but program failed — surface the last error log line
            logs = meta.get("logMessages", [])
            reason = next(
                (log for log in reversed(logs)
                 if any(kw in log.lower() for kw in ("failed", "error", "panic"))),
                str(error),
            )
            return {"success": False, "reason": reason, "fee_lamports": fee}

        except requests.exceptions.RequestException as e:
            print(f"[Tracker] Request failed ({attempt + 1}/{MAX_RETRIES}): {e}")
            time.sleep(RETRY_DELAY * (2 ** attempt))

    return {"success": None, "reason": "RPC failed after retries", "fee_lamports": None}
