# signer.py
import os
import base58
from dotenv import load_dotenv
from solders.keypair import Keypair
from solders.transaction import Transaction, VersionedTransaction
from solders.hash import Hash
from solders.instruction import Instruction
from solders.pubkey import Pubkey

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


def sign_legacy_transaction(
    instructions: list[Instruction], payer: Pubkey, recent_blockhash: Hash
) -> Transaction:
    """Build + sign a legacy Transaction from raw instructions (non-Jupiter flows,
    e.g. SPL Token CloseAccount)."""
    return Transaction.new_signed_with_payer(
        instructions, payer, [_KEYPAIR], recent_blockhash
    )
