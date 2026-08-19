# trading/dust_sweep.py
"""
Reclaims SOL rent locked in fully-empty SPL token accounts.

Every new-token BUY creates an Associated Token Account, which costs a
one-time ~0.002 SOL rent deposit. That deposit is refundable, but only if
something explicitly sends a CloseAccount instruction once the account's
balance hits zero — nothing else in the pipeline ever did that, so every
fully-sold-out position left its rent stranded on-chain permanently.

close_token_account(mint)   — called right after a SELL confirms; closes
                               that one account if it's now empty.
close_empty_token_accounts()— one-time sweep of every already-empty account
                               (dust left over from before this existed).
"""
import os

import requests
from dotenv import load_dotenv
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from solders.instruction import AccountMeta, Instruction
from solders.hash import Hash

from trading.signer import get_public_key, sign_legacy_transaction

load_dotenv()

_FALLBACK_RPC = "https://api.mainnet-beta.solana.com"
RPC_URL = os.getenv("ALCHEMY_RPC", _FALLBACK_RPC)

client = Client(RPC_URL)

TOKEN_PROGRAM      = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

_CLOSE_ACCOUNT_IX_DATA = bytes([9])  # SPL Token "CloseAccount" instruction index


def _rpc(method: str, params: list) -> dict:
    resp = requests.post(
        RPC_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"RPC {method} error: {body['error']}")
    return body.get("result", {})


def _latest_blockhash() -> Hash:
    result = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])
    return Hash.from_string(result["value"]["blockhash"])


def _fetch_empty_accounts(owner: str, program_id: str, mint_filter: str = None) -> list[dict]:
    result = _rpc("getTokenAccountsByOwner", [
        owner, {"programId": program_id}, {"encoding": "jsonParsed"},
    ])
    empties = []
    for acc in result.get("value", []):
        try:
            info = acc["account"]["data"]["parsed"]["info"]
            amount = int(info["tokenAmount"]["amount"])
            mint = info["mint"]
            if amount != 0:
                continue
            if mint_filter and mint != mint_filter:
                continue
            empties.append({
                "pubkey": acc["pubkey"],
                "mint": mint,
                "lamports": acc["account"]["lamports"],
                "program_id": program_id,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return empties


def _close_account(owner: Pubkey, acc: dict, blockhash: Hash) -> str:
    program_pk = Pubkey.from_string(acc["program_id"])
    account_pk = Pubkey.from_string(acc["pubkey"])
    ix = Instruction(
        program_pk,
        _CLOSE_ACCOUNT_IX_DATA,
        [
            AccountMeta(account_pk, is_signer=False, is_writable=True),
            AccountMeta(owner, is_signer=False, is_writable=True),
            AccountMeta(owner, is_signer=True, is_writable=False),
        ],
    )
    tx = sign_legacy_transaction([ix], owner, blockhash)
    sig = client.send_raw_transaction(bytes(tx)).value
    return str(sig)


def close_token_account(mint: str) -> dict:
    """Close a single token account for `mint` if its balance is now zero.
    Best-effort — call after a SELL confirms. Never raises."""
    try:
        owner_str = get_public_key()
        owner = Pubkey.from_string(owner_str)
        empties = (
            _fetch_empty_accounts(owner_str, TOKEN_PROGRAM, mint_filter=mint)
            + _fetch_empty_accounts(owner_str, TOKEN_2022_PROGRAM, mint_filter=mint)
        )
        if not empties:
            return {"closed": 0, "reclaimed_lamports": 0}

        blockhash = _latest_blockhash()
        acc = empties[0]
        sig = _close_account(owner, acc, blockhash)
        print(f"[DustSweep] Closed {mint[:12]}... reclaimed {acc['lamports']/1e9:.6f} SOL (tx {sig})")
        return {"closed": 1, "reclaimed_lamports": acc["lamports"], "signature": sig}
    except Exception as e:
        print(f"[DustSweep] Close failed for {mint[:12]}...: {e}")
        return {"closed": 0, "reclaimed_lamports": 0, "error": str(e)}


def close_empty_token_accounts() -> dict:
    """One-time (or periodic) sweep of every currently-empty token account."""
    owner_str = get_public_key()
    owner = Pubkey.from_string(owner_str)
    empties = (
        _fetch_empty_accounts(owner_str, TOKEN_PROGRAM)
        + _fetch_empty_accounts(owner_str, TOKEN_2022_PROGRAM)
    )
    if not empties:
        print("[DustSweep] No empty accounts to close.")
        return {"closed": 0, "reclaimed_lamports": 0}

    blockhash = _latest_blockhash()
    closed = 0
    reclaimed = 0
    for acc in empties:
        try:
            sig = _close_account(owner, acc, blockhash)
            closed += 1
            reclaimed += acc["lamports"]
            print(f"[DustSweep] Closed {acc['mint'][:12]}... "
                  f"reclaimed {acc['lamports']/1e9:.6f} SOL (tx {sig})")
        except Exception as e:
            print(f"[DustSweep] Failed to close {acc['mint'][:12]}...: {e}")

    print(f"[DustSweep] Done — {closed}/{len(empties)} closed, "
          f"{reclaimed/1e9:.6f} SOL reclaimed")
    return {"closed": closed, "reclaimed_lamports": reclaimed}


if __name__ == "__main__":
    close_empty_token_accounts()
