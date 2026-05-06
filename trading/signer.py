# signer.py
import os
import base58
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

load_dotenv()

# ---------- PRIVATE ZONE ----------
_PRIVATE_KEY_B58 = os.getenv("PRIVATE_KEY")
if not _PRIVATE_KEY_B58:
    raise RuntimeError("PRIVATE_KEY not found in environment")

_KEYPAIR = Keypair.from_bytes(base58.b58decode(_PRIVATE_KEY_B58))

# ---------- PUBLIC KEY ----------
_PUBLIC_KEY = os.getenv("PUBLIC_KEY")
if not _PUBLIC_KEY:
    _PUBLIC_KEY = str(_KEYPAIR.pubkey())

# ---------- PUBLIC INTERFACE ----------
def get_public_key() -> str:
    return _PUBLIC_KEY


def sign_transaction(tx: VersionedTransaction) -> VersionedTransaction:
    """
    Correct Solders signing for Jupiter v0 transactions
    """
    return VersionedTransaction(tx.message, [_KEYPAIR])
