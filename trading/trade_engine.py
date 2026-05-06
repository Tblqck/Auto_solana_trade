# trade_engine.py
import base64
import os
import time

import requests
from dotenv import load_dotenv
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from trading.signer import sign_transaction, get_public_key

load_dotenv()

_FALLBACK_RPC = "https://api.mainnet-beta.solana.com"
_PRIMARY_RPC = os.getenv("ALCHEMY_RPC", _FALLBACK_RPC)

client = Client(_PRIMARY_RPC)
wallet_pubkey = Pubkey.from_string(get_public_key())

JUPITER_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_SWAP  = "https://lite-api.jup.ag/swap/v1/swap"


def _http_get(url: str, params: dict, retries: int = 3) -> dict:
    delay = 1
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
            else:
                raise RuntimeError(f"GET {url} failed after {retries} attempts: {e}")


def _http_post(url: str, payload: dict, retries: int = 3) -> dict:
    delay = 1
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
            else:
                raise RuntimeError(f"POST {url} failed after {retries} attempts: {e}")


def execute_swap(
    input_mint: str,
    output_mint: str,
    amount_ui: float,
    input_decimals: int,
    slippage_bps: int = 50,
) -> dict:
    amount_in = int(amount_ui * (10 ** input_decimals))

    quote = _http_get(JUPITER_QUOTE, {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount_in,
        "slippageBps": slippage_bps,
    })

    if "routePlan" not in quote:
        raise RuntimeError(f"[Trade] Quote failed: {quote}")

    swap_resp = _http_post(JUPITER_SWAP, {
        "quoteResponse": quote,
        "userPublicKey": str(wallet_pubkey),
    })

    if "swapTransaction" not in swap_resp:
        raise RuntimeError(f"[Trade] Swap build failed: {swap_resp}")

    tx_bytes = base64.b64decode(swap_resp["swapTransaction"])
    tx = VersionedTransaction.from_bytes(tx_bytes)
    signed_tx = sign_transaction(tx)

    sig = client.send_raw_transaction(bytes(signed_tx)).value
    print(f"[Trade] Swap sent: {sig}")

    return {"signature": str(sig)}
