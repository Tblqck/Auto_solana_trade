import requests
import time

RPC_URL = "https://api.mainnet-beta.solana.com"
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

def check_trade_status(tx_sig: str) -> dict:
    """
    Check if a Solana transaction (e.g., Jupiter swap) succeeded or failed.

    Returns:
        dict: {
            "success": True | False | None (None = pending),
            "reason": str or None,
            "fee_lamports": int
        }
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_sig,
            {
                "encoding": "json",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(RPC_URL, json=payload, timeout=10).json()

            # -----------------------
            # RPC-level error
            # -----------------------
            if "error" in resp:
                code = resp["error"].get("code")
                msg = resp["error"].get("message", "")
                if code == 429 or "Too many requests" in msg:
                    print(f"⚠️ RPC rate limit hit, retry {attempt+1}/{MAX_RETRIES} in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY * (2 ** attempt))
                    continue
                return {"success": False, "reason": f"RPC Error: {resp['error']}", "fee_lamports": None}

            # -----------------------
            # Transaction not yet confirmed
            # -----------------------
            result = resp.get("result")
            if not result:
                return {"success": None, "reason": "Transaction not confirmed yet", "fee_lamports": None}

            # -----------------------
            # Extract meta
            # -----------------------
            meta = result.get("meta", {})
            error = meta.get("err")
            fee = meta.get("fee", 0)

            # -----------------------
            # Success
            # -----------------------
            if error is None:
                return {"success": True, "reason": None, "fee_lamports": fee}

            # -----------------------
            # Failed transaction
            # -----------------------
            logs = meta.get("logMessages", [])
            reason = None
            for log in reversed(logs):
                if "failed" in log.lower() or "error" in log.lower():
                    reason = log
                    break
            if not reason:
                reason = str(error)

            return {"success": False, "reason": reason, "fee_lamports": fee}

        except requests.exceptions.RequestException as e:
            print(f"⚠️ RPC request failed ({attempt+1}/{MAX_RETRIES}): {e}")
            time.sleep(RETRY_DELAY * (2 ** attempt))

    # If retries exhausted
    return {"success": None, "reason": "RPC request failed after retries", "fee_lamports": None}


# ------------------- Example usage -------------------
if __name__ == "__main__":
    tx_sig = "ZexQuVdTCEbg9ohJdgnuMFwrYrtR4X6drAjnH1WWw5NdBRtZPQkdixWDYt68Mnnsyp5oKsGsPRUX5qBnWYmfMsE"
    status = check_trade_status(tx_sig)
    print(status)
