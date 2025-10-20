from web3 import Web3

# Base RPC (can be dynamic if needed)
CHAIN_RPC = "https://arb1.arbitrum.io/rpc"

# Tokens
BASE_TOKEN = Web3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")  # WETH
QUOTE_TOKEN = Web3.to_checksum_address("0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9")  # USDT

# Uniswap v3 Router
UNISWAP_V3_ROUTER = Web3.to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564")

# Trade settings
USD_TO_SWAP = 5          # default swap amount
GAS_BUFFER_USD = 0.5       # minimum USD to leave for gas
SLIPPAGE_TOLERANCE = 0.5   # percent slippage allowed

# Gas settings
DEFAULT_MAX_FEE_GWEI = 1.5
DEFAULT_PRIORITY_FEE_GWEI = 1.0
