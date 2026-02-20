# trade_shadow.py

from trade_engine import execute_swap

# -----------------------------
# CONSTANTS
# -----------------------------
BASE_TOKEN_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
TOKEN_DECIMALS = {BASE_TOKEN_MINT: 6}


def register_token(mint: str, decimals: int):
    """Register token decimals for buy/sell calculations"""
    TOKEN_DECIMALS[mint] = decimals


# ========================
# SIGNAL HANDLER
# ========================
def handle_signal(signal: dict, wallet_snapshot: dict):
    """
    Generic signal handler.
    signal = {
        "type": "BUY" | "SELL",
        "token_mint": "<token mint address>",
        "amount": <float, in USDC if BUY>,
        "slippage_bps": 50 (optional)
    }

    wallet_snapshot:
        snapshot returned by get_wallet_state() at batch start
    """

    slippage = signal.get("slippage_bps", 50)
    token_mint = signal["token_mint"]

    # -----------------------------
    # BUY SIGNAL
    # -----------------------------
    if signal["type"] == "BUY":
        amount_usdc = signal["amount"]

        print(f"🟢 BUY SIGNAL → {amount_usdc} USDC → {token_mint}")

        tx = execute_swap(
            input_mint=BASE_TOKEN_MINT,
            output_mint=token_mint,
            amount_ui=amount_usdc,
            input_decimals=TOKEN_DECIMALS[BASE_TOKEN_MINT],
            slippage_bps=slippage
        )

        print("✅ BUY SENT:", tx["signature"])
        return tx

    # -----------------------------
    # SELL SIGNAL
    # -----------------------------
    elif signal["type"] == "SELL":

        token = next(
            (t for t in wallet_snapshot.get("tokens", [])
             if t["mint"] == token_mint),
            None
        )

        if not token or token["amount"] <= 0:
            raise RuntimeError(f"❌ SELL FAILED: No {token_mint} in wallet snapshot")

        # full balance (minus tiny epsilon)
        amount_ui = token["amount"] - 1e-6
        decimals = token["decimals"]

        register_token(token_mint, decimals)

        print(f"🔴 SELL SIGNAL → {amount_ui} of {token_mint} → USDC")

        tx = execute_swap(
            input_mint=token_mint,
            output_mint=BASE_TOKEN_MINT,
            amount_ui=amount_ui,
            input_decimals=decimals,
            slippage_bps=slippage
        )

        print("✅ SELL SENT:", tx["signature"])
        return tx

    else:
        raise ValueError(f"Unknown signal type: {signal['type']}")
