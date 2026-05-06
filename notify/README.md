# Notify Module Overview

## Overview
The `notify` module is responsible for managing notifications in the Solana trading bot. It interacts with Telegram to send updates regarding the data loop and wallet states.

### Files

#### 1. `__init__.py`
- **Purpose**: This file serves as an initializer for the `notify` package. It is currently empty but is necessary to indicate that the directory is a package.

#### 2. `reports.py`
- **Purpose**: Handles the accumulation of statistics from the data loop.
- **Key Functions**:
  - `accumulate_dataloop_stats(pairs_checked: int, rows_inserted: int)`: Accumulates statistics on data loop operations in a thread-safe manner.
  - `send_hourly_dataloop_report()`: Compiles and sends an hourly report of the data loop statistics to Telegram.
  - `send_hourly_wallet_report()`: Fetches wallet state information and sends it as a notification to Telegram.

#### 3. `telegram.py`
- **Purpose**: Integrates with the Telegram API to send notifications.
- **Key Functions**:
  - `send(text: str)`: Posts a message to a Telegram chat configured with a bot token.
  - **Configuration**: The bot token is loaded from the environment variable `Trade_crpyt`, and the chat ID is hardcoded.

### Usage
To utilize the notify module, ensure that the necessary environment variables are set, and call the appropriate functions for sending reports and notifications.

---
