# signer.py
import os
import base58
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

load_dotenv()  # load .env

# ---------- PRIVATE ZONE ----------
__PRIVATE_KEY_B58 = os.getenv("PRIVATE_KEY")
if not __PRIVATE_KEY_B58:
    raise RuntimeError("PRIVATE_KEY not found in environment")

__KEYPAIR = Keypair.from_bytes(
    base58.b58decode(__PRIVATE_KEY_B58)
)

# ---------- PUBLIC KEY ----------
__PUBLIC_KEY = os.getenv("PUBLIC_KEY")  # optional, for backup
if not __PUBLIC_KEY:
    __PUBLIC_KEY = str(__KEYPAIR.pubkey())  # derive if not set

# ---------- PUBLIC INTERFACE ----------
def sign_transaction(tx: VersionedTransaction) -> VersionedTransaction:
    """
    Sign a Solana VersionedTransaction using solders API.
    Returns a signed VersionedTransaction.
    """
    # tx.try_sign returns a new signed transaction
    signed_tx = tx.try_sign([__KEYPAIR])
    return signed_tx

def get_public_key() -> str:
    """
    Returns the public key (wallet address) safely.
    """
    return __PUBLIC_KEY
