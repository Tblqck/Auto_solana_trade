"""
trading/liquidate.py

Sells ALL token positions back to USDC in one pass.
Skips USDC and SOL (base tokens).

Usage:
    python trading/liquidate.py
"""

from wallet.wallet_state import get_spl_token_balances
from trading.trade_engine import execute_swap

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WSOL_MINT = "So11111111111111111111111111111111111111112"
SKIP      = {USDC_MINT, WSOL_MINT}


def liquidate_all():
    tokens = get_spl_token_balances()
    to_sell = [t for t in tokens if t["mint"] not in SKIP and t["amount"] > 0]

    if not to_sell:
        print("[Liquidate] Nothing to sell.")
        return

    print(f"[Liquidate] {len(to_sell)} position(s) to sell -> USDC\n")

    for token in to_sell:
        mint     = token["mint"]
        amount   = token["amount"]
        decimals = token["decimals"]
        short    = mint[:16] + "..."

        print(f"[Liquidate] Selling {amount} of {short}")
        try:
            result = execute_swap(
                input_mint    = mint,
                output_mint   = USDC_MINT,
                amount_ui     = amount,
                input_decimals= decimals,
                slippage_bps  = 100,   # 1% slippage — wider for illiquid meme coins
            )
            print(f"[Liquidate] OK  tx: {result['signature']}")
        except Exception as e:
            print(f"[Liquidate] FAILED {short}: {e}")

    print("\n[Liquidate] Done.")


if __name__ == "__main__":
    liquidate_all()
