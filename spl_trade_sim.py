import requests
import base64
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from signer import sign_transaction, get_public_key

# -------------------------
# CONFIG
# -------------------------
RPC_URL = "https://api.mainnet-beta.solana.com"

JUPITER_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_SWAP  = "https://lite-api.jup.ag/swap/v1/swap"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

USDC_DECIMALS = 6
AMOUNT_USDC = 1.0           # 🔴 REAL MONEY
SLIPPAGE_BPS = 50           # 0.5%

# -------------------------
# SETUP
# -------------------------
client = Client(RPC_URL)
wallet_pubkey = Pubkey.from_string(get_public_key())

amount_in = int(AMOUNT_USDC * 10**USDC_DECIMALS)

# -------------------------
# 1. GET QUOTE
# -------------------------
quote_params = {
    "inputMint": USDC_MINT,
    "outputMint": USDT_MINT,
    "amount": amount_in,
    "slippageBps": SLIPPAGE_BPS,
}

quote = requests.get(JUPITER_QUOTE, params=quote_params).json()

if "routePlan" not in quote:
    raise RuntimeError(f"Quote failed: {quote}")

# -------------------------
# 2. BUILD SWAP TX
# -------------------------
swap_payload = {
    "quoteResponse": quote,
    "userPublicKey": str(wallet_pubkey),
    "wrapAndUnwrapSol": True,
}

swap_resp = requests.post(JUPITER_SWAP, json=swap_payload).json()

if "swapTransaction" not in swap_resp:
    raise RuntimeError(f"Swap build failed: {swap_resp}")

tx_b64 = swap_resp["swapTransaction"]

# -------------------------
# 3. SIGN TRANSACTION
# -------------------------
tx_bytes = base64.b64decode(tx_b64)
tx = VersionedTransaction.from_bytes(tx_bytes)
signed_tx = sign_transaction(tx)

# -------------------------
# 4. SEND TRANSACTION
# -------------------------
sig = client.send_raw_transaction(bytes(signed_tx)).value

print("✅ SWAP SENT")
print("TX:", sig)
