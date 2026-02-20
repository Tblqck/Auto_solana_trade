import requests
import json
import time
import csv
from solders.pubkey import Pubkey
from signer import get_public_key

RPC_URL = "https://api.mainnet-beta.solana.com"
wallet_pubkey = Pubkey.from_string(get_public_key())

# ---- Known mints ----
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# CoinGecko IDs (only needed for non-stable assets)
COINGECKO_IDS = {
    "SOL": "solana",
}

# ---- Decimals registry
TOKEN_DECIMALS = {}

def register_token(mint: str, decimals: int):
    """Register token decimals for buy/sell calculations"""
    TOKEN_DECIMALS[mint] = decimals

# ---- SOL price cache
SOL_PRICE_CACHE = None

# ----------------------
# Safe RPC request
# ----------------------
def safe_rpc_request(payload: dict, retries=3, delay=1) -> dict:
    """Send an RPC request with retry logic and exponential backoff"""
    current_delay = delay
    for attempt in range(retries):
        try:
            resp = requests.post(RPC_URL, json=payload, timeout=10)
            resp.raise_for_status()
            resp_json = resp.json()
            if "error" in resp_json:
                code = resp_json["error"].get("code")
                if code == 429:
                    print(f"⚠️ RPC rate limit hit, retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= 2
                    continue
                raise RuntimeError(f"RPC Error: {resp_json['error']}")
            return resp_json if "result" in resp_json else {"result": {}}
        except (requests.exceptions.RequestException, RuntimeError, json.JSONDecodeError) as e:
            print(f"⚠️ RPC attempt {attempt + 1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(current_delay)
                current_delay *= 2
            else:
                print("⚠️ RPC request failed, returning empty result")
                return {"result": {}}

def get_spl_token_balances() -> list[dict]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            str(wallet_pubkey),
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }

    resp = safe_rpc_request(payload)
    result = resp.get("result", {})

    # Bail early if no value
    if not result or "value" not in result:
        return []

    tokens = []
    for acc in result["value"]:
        info = acc["account"]["data"]["parsed"]["info"]
        amount = int(info["tokenAmount"]["amount"])
        decimals = int(info["tokenAmount"]["decimals"])
        ui_amount = amount / (10 ** decimals)

        if ui_amount > 0:
            tokens.append({
                "mint": info["mint"],
                "amount": ui_amount,
                "decimals": decimals
            })

    return tokens

# ----------------------
# Wallet balances
# ----------------------
def get_sol_balance() -> float:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [str(wallet_pubkey)]
    }
    resp = safe_rpc_request(payload)
    lamports = resp.get("result", {}).get("value", 0)
    return lamports / 1_000_000_000



def get_token_balance(mint: str) -> dict | None:
    """Return token balance + decimals for a given mint"""
    tokens = get_spl_token_balances()
    for token in tokens:
        if token["mint"] == mint:
            return token
    return None

# ----------------------
# CoinGecko price
# ----------------------
def get_token_price_usd(coingecko_id: str, retries=3, delay=1) -> float:
    """Get token price in USD with retries and fallback to cache"""
    global SOL_PRICE_CACHE
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

        print(f"⚠️ CoinGecko attempt {attempt + 1} failed for {coingecko_id}, retrying in {current_delay}s...")
        time.sleep(current_delay)
        current_delay *= 2

    if coingecko_id == "solana" and SOL_PRICE_CACHE:
        print("⚠️ Using cached SOL price due to CoinGecko failure")
        return SOL_PRICE_CACHE

    print(f"⚠️ CoinGecko failed, returning default price for {coingecko_id}")
    return 1.0 if coingecko_id == "solana" else 0.0

# ----------------------
# Wallet state
# ----------------------
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
        "total_usd": sol_usd
    }

    for token in tokens:
        mint = token["mint"]
        amount = token["amount"]
        token_data = token.copy()

        # ---- Stablecoins
        if mint in [USDC_MINT, USDT_MINT]:
            token_data["usd_value"] = amount
            wallet_data["total_usd"] += amount

        # ---- Other priced assets
        elif mint in COINGECKO_IDS:
            price = get_token_price_usd(COINGECKO_IDS[mint])
            usd_value = amount * price
            token_data["usd_value"] = usd_value
            wallet_data["total_usd"] += usd_value

        # ---- Unknown assets
        else:
            token_data["usd_value"] = None

        wallet_data["tokens"].append(token_data)

    return wallet_data

# ----------------------
# Save wallet snapshot to CSV
# ----------------------
def save_wallet_csv(wallet: dict, fees_accum_usd: float, filename="wallet_state.csv"):
    """Save wallet snapshot to a CSV file"""
    try:
        with open(filename, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "public_key", "sol_balance", "sol_usd", "total_usd",
                "token_mint", "token_amount", "token_decimals", "token_usd_value", "fees_accum_usd"
            ])
            for token in wallet.get("tokens", []):
                writer.writerow([
                    wallet.get("public_key"),
                    wallet.get("sol_balance"),
                    wallet.get("sol_usd"),
                    wallet.get("total_usd"),
                    token.get("mint"),
                    token.get("amount"),
                    token.get("decimals"),
                    token.get("usd_value"),
                    fees_accum_usd
                ])
        print(f"💾 Wallet saved to {filename}")
    except Exception as e:
        print(f"⚠️ Failed to save wallet CSV: {e}")

# ----------------------
# Run as script continuously
# ----------------------
if __name__ == "__main__":
    fees_accum = 0
    while True:
        print("📊 Fetching current wallet state...")
        state = get_wallet_state()
        print(json.dumps(state, indent=2))
        save_wallet_csv(state, fees_accum)
        fees_accum += 0  # Update fees if you track them
        time.sleep(10)  # run every 10 seconds (adjust as needed)
