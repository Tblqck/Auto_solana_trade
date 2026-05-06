# sol_trade

Fully automated Solana DEX trading bot. Scrapes token pairs and OHLC data, runs ML models to generate BUY signals, applies risk filters and stoploss management, then executes on-chain swaps via Jupiter.

---

## System Architecture

```
main.py (12-hour session orchestrator)
   │
   ├─ data/get_pairs.py          ← one-shot pair scrape
   ├─ data/Data_Loop.py          ← background OHLC agent (daemon thread)
   └─ ai/aibot.py                ← AI bot (launches watcher internally)
          │
          └─ signals/watcher.py  ← main daemon loop
                 │
                 ├─ data/Data_Loop_core.py     ← DEX scrape → DB
                 └─ signals/watcher_core.py    ← signal pipeline → trade queue
                        │
                        └─ signals/signal_pipeline.py
                               │
                               ├─ ai/ai_orch.py              ← ML predictions
                               ├─ risk/entry.py              ← LossGuard scan
                               ├─ risk/stoploss_orchestrator.py
                               └─ risk/stoploss_tightener_orch.py
                                      │
                                      └─ trading/trade.py    ← subprocess
                                             │
                                             ├─ trading/trade_2.py
                                             ├─ trading/trade_executor.py
                                             ├─ trading/trade_orch_pipeline.py
                                             ├─ trading/trade_shadow.py
                                             ├─ trading/trade_engine.py   ← Jupiter RPC
                                             └─ trading/signer.py         ← Solana keypair
```

---

## Dependency Layers

```
core          ← no local dependencies
  ↑
data          ← depends on core
  ↑
ai            ← depends on core
  ↑
risk          ← depends on core
  ↑
signals       ← depends on core, ai, risk, data
  ↑
wallet        ← depends on core
  ↑
trading       ← depends on core, wallet
  ↑
sync          ← depends on core, data          (standalone scripts)
simulation    ← depends on core, data          (dev/backtesting only)
utils         ← depends on core               (stateless helpers)
tests         ← depends on all layers          (debug/inspection only)
scripts       ← dev tools, not in pipeline
```

---

## Folder Overview

| Folder | Role |
|---|---|
| `core/` | Shared foundation — DB connections, config, schema |
| `data/` | DEX pair scraper + OHLC ingestion |
| `ai/` | ML signal generation (classifier + regressor) |
| `risk/` | LossGuard, hard-stop, trailing-stop, tightener |
| `signals/` | Signal pipeline orchestrator + watcher daemon |
| `trading/` | Jupiter swap execution, signer, trade tracker |
| `wallet/` | On-chain balance queries, USDC allocation slots |
| `sync/` | AWS EC2 ↔ local SQLite bridge + sync scripts |
| `utils/` | Stateless helpers (controller CSV, fallback SELL) |
| `notify/` | Telegram notifications, report accumulator |
| `simulation/` | Dev-only replay and backtesting (not deployed) |
| `models/` | Pickled sklearn classifier + regressor |
| `tests/` | Debug and inspection scripts |
| `scripts/` | Dev tools, not in live pipeline |
| `db_files/` | SQLite databases (not committed — see below) |

---

## Databases

Databases are **not committed to git**. The `db_files/` folder is tracked but all `.db` files are ignored.

| File | Purpose |
|---|---|
| `db_files/dex_pipeline.db` | Primary live DB (mirrored on AWS EC2) |
| `db_files/dex_pipeline_local_mod.db` | Local working DB for signal pipeline |
| `db_files/dex_pipeline_local_sim_mod.db` | Simulation source DB |
| `db_files/dex_pipeline_archive.db` | Local archive synced from AWS |

Schema is auto-created at startup via `core/db_schema/db_creator.py`.

---

## Key Tables

| Table | Purpose |
|---|---|
| `tokens` | Raw token metadata from DEX |
| `supported_tokens` | Filtered tokens eligible for trading |
| `ohlc_data` | 1-minute OHLC price candles |
| `ai_thought` | ML signal output per pair_id |
| `pending_trades` | Queued trades waiting for execution |
| `live_trades` | Currently open positions |
| `trade_risk_state` | Per-pair stoploss state (entry, peak, stop prices) |
| `loss_guard_log` | LossGuard scan history |
| `module_control` | ON/OFF flags per subsystem |
| `module_status` | Last-run timestamps per module |

---

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in secrets
cp .env.example .env

# Run preflight checks
python preflight.py

# Launch (12-hour session)
python main.py
```

---

## Running Individual Components

```bash
# Data loop only
python data/Data_Loop.py

# AI bot only
python ai/aibot.py

# Watcher daemon (signal pipeline + trade trigger)
python signals/watcher.py

# AWS data sync pipeline
python sync/update_pipeline.py

# Simulation — batch load 24h of OHLC
python simulation/data_loop_sim.py --initial

# Simulation — stream one row at a time
python simulation/data_loop_stream.py
```

---

## Config

| File | Purpose |
|---|---|
| `config.yaml` | DB paths, ML model paths, feature columns, probability threshold |
| `.env` | Wallet private key, Alchemy RPC URL, API keys — **never commit** |
| `master_control.csv` | ON/OFF flags: `AI_BOT`, `WATCHER`, `DataLoop`, `Get-pairs` |
| `controller.csv` | Runtime status flags |

---

## ML Models

| File | Role |
|---|---|
| `models/model_classifier.pkl` | Outputs `clf_prob` — probability of BUY signal |
| `models/model_regressor.pkl` | Outputs `reg_pred` — price movement prediction |

Feature columns and probability threshold are configured in `config.yaml`.
