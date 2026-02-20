# spl_trade_sim.py
import os
import json
import requests
from solana.rpc.api import Client
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.transaction import Transaction
from solana.rpc.types import TxOpts
from dotenv import load_dotenv

load_dotenv()  # load PRIVATE_KEY from .env

# -------------------------
# CONFIG
# -------------------------
RPC_URL = "https://api.mainnet-beta.solana.com"
JUPITER_QUOTE = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP = "https://quote-api.jup.ag/v6/swap"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDC_DECIMALS = 6
USD_TO_SWAP = 1.0

# -------------------------
# LOAD WALLET
# -------------------------
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
if not PRIVATE_KEY:
    raise RuntimeError("PRIVATE_KEY not set in .env")

key_bytes = bytes([int(x) for x in PRIVATE_KEY.split(",")])
wallet = Keypair.from_secret_key(key_bytes)
wallet_pubkey = wallet.public_key

client = Client(RPC_URL)

# -------------------------
# WALLET STATE
# -------------------------
def get_wallet_state():
    """Return SPL tokens and SOL balance."""
    sol_balance = client.get_balance(wallet_pubkey)["result"]["value"] / 1_000_000_000

    # fetch SPL tokens
    opts = {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "encoding": "jsonParsed"}
    resp = client.get_token_accounts_by_owner(wallet_pubkey, opts)
    tokens = []
    for acc in resp['result']['value']:
        info = acc['account']['data']['parsed']['info']
        amt = int(info["tokenAmount"]["amount"])
        dec = int(info["tokenAmount"]["decimals"])
        ui = amt / (10 ** dec)
        if ui > 0:
            tokens.append({"mint": info["mint"], "amount": ui})
    return {"public_key": str(wallet_pubkey), "sol_balance": sol_balance, "tokens": tokens}

# -------------------------
# GET JUPITER QUOTE
# -------------------------
amount_in = int(USD_TO_SWAP * 10**USDC_DECIMALS)
quote_params = {
    "inputMint": USDC_MINT,
    "outputMint": USDT_MINT,
    "amount": amount_in,
    "slippageBps": 50
}
quote = requests.get(JUPITER_QUOTE, params=quote_params).json()

if "data" not in quote or not quote["data"]:
    raise RuntimeError(f"Failed to get quote: {quote}")

route = quote["data"][0]

# -------------------------
# BUILD SWAP TRANSACTION
# -------------------------
swap_payload = {
    "userPublicKey": str(wallet_pubkey),
    "quoteResponse": route,
    "wrapAndUnwrapSOL": True
}
swap_resp = requests.post(JUPITER_SWAP, json=swap_payload).json()

if "swapTransaction" not in swap_resp:
    raise RuntimeError(f"Failed to get swap transaction: {swap_resp}")

swap_tx_b64 = swap_resp["swapTransaction"]

# -------------------------
# SIGN & SEND TRANSACTION
# -------------------------
from base64 import b64decode
from solana.transaction import Transaction

tx_bytes = b64decode(swap_tx_b64)
tx = Transaction.deserialize(tx_bytes)
tx.sign(wallet)

sig = client.send_transaction(tx, wallet, opts=TxOpts(skip_confirmation=False))
print("✅ Swap TX sent:", sig["result"])

# -------------------------
# BEFORE / AFTER STATE
# -------------------------
before = get_wallet_state()
after = get_wallet_state()

# -------------------------
# REPORT
# -------------------------
report = {
    "before": before,
    "after": after,
    "swap": {
        "from": "USDC",
        "to": "USDT",
        "usd_swapped": USD_TO_SWAP,
        "expected_out": int(route["outAmount"]) / 10**6
    },
    "tx": sig["result"]
}

print(json.dumps(report, indent=2))
