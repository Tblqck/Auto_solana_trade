import os
import requests
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from solders.pubkey import Pubkey
from trading.signer import get_public_key

load_dotenv()
RPC_URL = os.getenv("ALCHEMY_RPC", "https://api.mainnet-beta.solana.com")
wallet_pubkey = Pubkey.from_string(get_public_key())

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# Legacy SPL Token program and Token-2022 (Token Extensions) program
_TOKEN_PROGRAM     = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
_TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

COINGECKO_IDS = {
    "SOL": "solana",
}

TOKEN_DECIMALS = {}

SOL_PRICE_CACHE = None


def register_token(mint: str, decimals: int):
    TOKEN_DECIMALS[mint] = decimals


def safe_rpc_request(payload: dict, retries=3, delay=1) -> dict:
    current_delay = delay
    for attempt in range(retries):
        try:
            resp = requests.post(RPC_URL, json=payload, timeout=10)
            resp.raise_for_status()
            resp_json = resp.json()
            if "error" in resp_json:
                code = resp_json["error"].get("code")
                if code == 429:
                    print(f"[Wallet] RPC rate limit, retrying in {current_delay}s")
                    time.sleep(current_delay)
                    current_delay *= 2
                    continue
                raise RuntimeError(f"RPC Error: {resp_json['error']}")
            return resp_json if "result" in resp_json else {"result": {}}
        except (requests.exceptions.RequestException, RuntimeError, json.JSONDecodeError) as e:
            print(f"[Wallet] RPC attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(current_delay)
                current_delay *= 2
            else:
                return {"result": {}}


def _fetch_token_accounts_for_program(program_id: str) -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            str(wallet_pubkey),
            {"programId": program_id},
            {"encoding": "jsonParsed"},
        ],
    }
    resp = safe_rpc_request(payload)
    result = resp.get("result", {})
    if not result or "value" not in result:
        return []

    tokens = []
    for acc in result["value"]:
        try:
            info = acc["account"]["data"]["parsed"]["info"]
            amount = int(info["tokenAmount"]["amount"])
            decimals = int(info["tokenAmount"]["decimals"])
            ui_amount = amount / (10 ** decimals)
            if ui_amount > 0:
                tokens.append({
                    "mint": info["mint"],
                    "amount": ui_amount,
                    "amount_raw": amount,
                    "decimals": decimals,
                    "pubkey": acc.get("pubkey"),
                    "program_id": program_id,
                })
        except (KeyError, TypeError, ValueError):
            continue
    return tokens


def get_spl_token_balances() -> list[dict]:
    """Fetch all SPL token balances — queries both legacy Token Program and Token-2022."""
    legacy  = _fetch_token_accounts_for_program(_TOKEN_PROGRAM)
    t2022   = _fetch_token_accounts_for_program(_TOKEN_2022_PROGRAM)
    print(f"[Wallet] Legacy tokens: {len(legacy)}, Token-2022 tokens: {len(t2022)}")
    return legacy + t2022


def get_sol_balance() -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [str(wallet_pubkey)],
    }
    resp = safe_rpc_request(payload)
    lamports = resp.get("result", {}).get("value", 0)
    return lamports / 1_000_000_000


def get_token_balance(mint: str) -> dict | None:
    tokens = get_spl_token_balances()
    for token in tokens:
        if token["mint"] == mint:
            return token
    return None


_JUPITER_QUOTE_URL = "https://lite-api.jup.ag/swap/v1/quote"
_SOL_MINT_ADDR     = "So11111111111111111111111111111111111111112"
_USDC_MINT_ADDR    = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _get_sol_price_jupiter() -> float | None:
    """Derive SOL/USD from a Jupiter quote: 1 SOL -> USDC."""
    try:
        resp = requests.get(
            _JUPITER_QUOTE_URL,
            params={
                "inputMint":   _SOL_MINT_ADDR,
                "outputMint":  _USDC_MINT_ADDR,
                "amount":      1_000_000_000,   # 1 SOL in lamports
                "slippageBps": 50,
            },
            timeout=5,
        ).json()
        out_amount = resp.get("outAmount")
        if out_amount is not None:
            return float(out_amount) / 1_000_000   # USDC has 6 decimals
    except Exception:
        pass
    return None


def _get_token_usd_value_jupiter(mint: str, decimals: int, amount: float) -> float | None:
    """Price any token in USD by quoting amount tokens -> USDC via Jupiter."""
    try:
        raw_amount = int(amount * (10 ** decimals))
        if raw_amount <= 0:
            return None
        resp = requests.get(
            _JUPITER_QUOTE_URL,
            params={
                "inputMint":   mint,
                "outputMint":  _USDC_MINT_ADDR,
                "amount":      raw_amount,
                "slippageBps": 50,
            },
            timeout=5,
        ).json()
        out_amount = resp.get("outAmount")
        if out_amount is not None:
            return float(out_amount) / 1_000_000   # USDC has 6 decimals
    except Exception:
        pass
    return None


def get_token_price_usd(coingecko_id: str, retries=3, delay=1) -> float:
    global SOL_PRICE_CACHE

    # For SOL: try Jupiter first (already verified live by preflight)
    if coingecko_id == "solana":
        price = _get_sol_price_jupiter()
        if price:
            SOL_PRICE_CACHE = price
            return price
        print("[Wallet] Jupiter price failed — falling back to CoinGecko")

    current_delay = delay
    for attempt in range(retries):
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd"
            resp = requests.get(url, timeout=5).json()
            price = resp.get(coingecko_id, {}).get("usd")
            if price is not None:
                if coingecko_id == "solana":
                    SOL_PRICE_CACHE = price
                return price
        except requests.exceptions.RequestException:
            pass

        print(f"[Wallet] CoinGecko attempt {attempt + 1} failed for {coingecko_id}, retrying in {current_delay}s")
        time.sleep(current_delay)
        current_delay *= 2

    if coingecko_id == "solana" and SOL_PRICE_CACHE:
        print("[Wallet] Using cached SOL price")
        return SOL_PRICE_CACHE

    print(f"[Wallet] All price sources failed for {coingecko_id} — returning 0.0")
    return 0.0


def get_wallet_state() -> dict:
    sol_balance = get_sol_balance()
    tokens = get_spl_token_balances()

    sol_price = get_token_price_usd(COINGECKO_IDS["SOL"])
    sol_usd = sol_balance * sol_price

    wallet_data = {
        "public_key": str(wallet_pubkey),
        "sol_balance": sol_balance,
        "sol_usd": sol_usd,
        "tokens": [],
        "total_usd": sol_usd,
    }

    for token in tokens:
        mint = token["mint"]
        amount = token["amount"]
        token_data = token.copy()

        if mint in [USDC_MINT, USDT_MINT]:
            token_data["usd_value"] = amount
            wallet_data["total_usd"] += amount
        elif mint in COINGECKO_IDS:
            price = get_token_price_usd(COINGECKO_IDS[mint])
            token_data["usd_value"] = amount * price
            wallet_data["total_usd"] += token_data["usd_value"]
        else:
            usd = _get_token_usd_value_jupiter(mint, token["decimals"], amount)
            token_data["usd_value"] = usd
            if usd is not None:
                wallet_data["total_usd"] += usd
            else:
                print(f"[Wallet] No price found for {mint} (not on Jupiter)")

        wallet_data["tokens"].append(token_data)

    return wallet_data


def save_wallet_db(wallet: dict, fees_accum_usd: float):
    """Persist a wallet snapshot to the wallet_snapshots + wallet_tokens tables."""
    try:
        from core.db_utils import get_db_connection
        usdc_balance = next(
            (t["amount"] for t in wallet.get("tokens", []) if t["mint"] == USDC_MINT),
            0.0,
        )
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO wallet_snapshots
                (timestamp, sol_balance, sol_usd, usdc_balance, total_usd, fees_accum_usd)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            wallet.get("sol_balance"),
            wallet.get("sol_usd"),
            usdc_balance,
            wallet.get("total_usd"),
            fees_accum_usd,
        ))
        snapshot_id = cur.lastrowid
        for token in wallet.get("tokens", []):
            cur.execute("""
                INSERT INTO wallet_tokens
                    (snapshot_id, token_mint, token_amount, token_decimals, token_usd_value)
                VALUES (?, ?, ?, ?, ?)
            """, (
                snapshot_id,
                token.get("mint"),
                token.get("amount"),
                token.get("decimals"),
                token.get("usd_value"),
            ))
        conn.commit()
        conn.close()
        print("[Wallet] Saved to DB")
    except Exception as e:
        print(f"[Wallet] Failed to save to DB: {e}")


if __name__ == "__main__":
    fees_accum = 0
    print("[Wallet] Fetching wallet state...")
    state = get_wallet_state()
    print(json.dumps(state, indent=2))
    save_wallet_db(state, fees_accum)
