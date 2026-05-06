# trade_shadow.py
from trading.trade_engine import execute_swap
from wallet.wallet_state import get_token_balance

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT  = "So11111111111111111111111111111111111111112"

TOKEN_DECIMALS = {
    USDC_MINT: 6,
    SOL_MINT:  9,
}


def register_token(mint: str, decimals: int):
    TOKEN_DECIMALS[mint] = decimals


def handle_signal(signal: dict, wallet_snapshot: dict) -> dict:
    """
    Accepted signal types:

      REFILL  swap USDC -> SOL to top up gas wallet (fires automatically)
      BUY     swap USDC -> token
      SELL    swap token -> USDC (fetches fresh on-chain balance)

    All return {"signature": str}.
    """
    slippage   = signal.get("slippage_bps", 50)
    token_mint = signal["token_mint"]

    # ── REFILL: USDC -> native SOL ───────────────────────────────────────────
    if signal["type"] == "REFILL":
        amount_usdc = signal["amount"]
        print(f"[Trade] REFILL {amount_usdc:.4f} USDC -> SOL (gas top-up)")
        tx = execute_swap(
            input_mint=USDC_MINT,
            output_mint=SOL_MINT,
            amount_ui=amount_usdc,
            input_decimals=TOKEN_DECIMALS[USDC_MINT],
            slippage_bps=slippage,
        )
        print(f"[Trade] REFILL sent: {tx['signature']}")
        return tx

    # ── BUY: USDC -> token ───────────────────────────────────────────────────
    elif signal["type"] == "BUY":
        amount_usdc = signal["amount"]
        print(f"[Trade] BUY {amount_usdc:.4f} USDC -> {token_mint}")
        tx = execute_swap(
            input_mint=USDC_MINT,
            output_mint=token_mint,
            amount_ui=amount_usdc,
            input_decimals=TOKEN_DECIMALS[USDC_MINT],
            slippage_bps=slippage,
        )
        print(f"[Trade] BUY sent: {tx['signature']}")
        return tx

    # ── SELL: token -> USDC ──────────────────────────────────────────────────
    elif signal["type"] == "SELL":
        # Always fetch fresh on-chain balance — snapshot can be stale
        token = get_token_balance(token_mint)

        if not token or token["amount"] <= 0:
            raise RuntimeError(f"[Trade] SELL failed: no {token_mint} balance on-chain")

        decimals = token["decimals"]
        register_token(token_mint, decimals)

        # Subtract 1 raw unit to avoid rounding overflow on-chain
        amount_raw = int(token["amount"] * (10 ** decimals)) - 1
        if amount_raw <= 0:
            raise RuntimeError(f"[Trade] SELL amount too small for {token_mint}")
        amount_ui = amount_raw / (10 ** decimals)

        print(f"[Trade] SELL {amount_ui:.6f} of {token_mint} -> USDC")
        tx = execute_swap(
            input_mint=token_mint,
            output_mint=USDC_MINT,
            amount_ui=amount_ui,
            input_decimals=decimals,
            slippage_bps=slippage,
        )
        print(f"[Trade] SELL sent: {tx['signature']}")
        return tx

    else:
        raise ValueError(f"[Trade] Unknown signal type: {signal['type']}")
