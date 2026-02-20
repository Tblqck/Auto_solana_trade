# trade_engine.py
import requests
import base64

from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from signer import sign_transaction, get_public_key

RPC_URL = "https://api.mainnet-beta.solana.com"
JUPITER_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_SWAP  = "https://lite-api.jup.ag/swap/v1/swap"

client = Client(RPC_URL)
wallet_pubkey = Pubkey.from_string(get_public_key())


def execute_swap(
    input_mint: str,
    output_mint: str,
    amount_ui: float,
    input_decimals: int,
    slippage_bps: int = 50,
) -> dict:
    """
    Executes a Jupiter swap.

    IMPORTANT:
    This function ONLY:
      - gets quote
      - builds swap tx
      - signs
      - sends

    It DOES NOT check confirmation.
    Orchestrator owns confirmation & retries.
    """

    amount_in = int(amount_ui * (10 ** input_decimals))

    # -----------------------------
    # 1. Quote
    # -----------------------------
    quote_params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount_in,
        "slippageBps": slippage_bps,
    }

    quote = requests.get(JUPITER_QUOTE, params=quote_params, timeout=15).json()
    if "routePlan" not in quote:
        raise RuntimeError(f"Quote failed: {quote}")

    # -----------------------------
    # 2. Build swap transaction
    # -----------------------------
    swap_payload = {
        "quoteResponse": quote,
        "userPublicKey": str(wallet_pubkey),
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": "auto",
    }

    swap_resp = requests.post(JUPITER_SWAP, json=swap_payload, timeout=15).json()
    if "swapTransaction" not in swap_resp:
        raise RuntimeError(f"Swap build failed: {swap_resp}")

    # -----------------------------
    # 3. Sign
    # -----------------------------
    tx_bytes = base64.b64decode(swap_resp["swapTransaction"])
    tx = VersionedTransaction.from_bytes(tx_bytes)
    signed_tx = sign_transaction(tx)

    # -----------------------------
    # 4. Send
    # -----------------------------
    sig = str(client.send_raw_transaction(bytes(signed_tx)).value)

    print(f"📤 Trade sent: {sig}")

    # -----------------------------
    # 5. Return ONLY signature
    # -----------------------------
    return {
        "signature": sig
    }
