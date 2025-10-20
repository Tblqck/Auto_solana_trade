# 🧠 Solana Auto-Trade System (Private Core)

> ⚠️ **Note:** This repository contains a redacted version of a private automated trading system.  
> Core modules, model weights, and strategy logic are intentionally omitted for confidentiality.  
> For licensing or usage inquiries, contact the author directly.

---

## 🚀 Overview

This project is a **modular AI-driven auto trading framework** built to autonomously trade tokens on the **Solana blockchain**.  
It integrates data ingestion, AI signal generation, and live execution logic across separate coordinated modules, controlled through a single master control file.

The system is designed for **long uptime**, **fault tolerance**, and **graceful recovery**, operating continuously with automated archiving and state resets.

---

## 🧩 Architecture

### 1. `main.py` — System Orchestrator  
Handles:
- Full lifecycle automation: archive, reset, launch, monitor, and shutdown.  
- Sequential execution of subsystems: `get-pairs`, `DataLoop`, and `AI Bot`.  
- Master control via `master_control.csv` for toggling modules (`AI_BOT`, `WATCHER`, `DataLoop`, `Get-pairs`).  
- 12-hour runtime loop with safe termination.

### 2. `DataLoop.py` — Market Data Engine  
Responsible for:
- Fetching live OHLC data from **GeckoTerminal API** for Solana pools.  
- Filling missing candles, cleaning, and maintaining structured time-series data.  
- Writing rotation metadata (`dataloop_status.csv`) for sync confirmation with the main process.  
- Self-regulated loop execution via CSV-based ON/OFF toggle.

### 3. `aibot.py` — AI Decision Core  
The heart of the system:
- Loads two trained models (`classifier` + `regressor`) for trade signal generation.  
- Reads feature-engineered OHLC data, predicts trade probability & expected return.  
- Generates BUY/NO_TRADE signals and dispatches valid opportunities to the Watcher module.  
- Designed to run continuously with adaptive sleep intervals and CSV-based interprocess sync.

### 4. `watcher.py` (Redacted)  
Handles transaction dispatch and monitoring.  
- Verifies contract health, on-chain liquidity, and transaction receipts.  
- Executes validated signals and logs trading outcomes to CSV books.  
- Communicates with controller files for safe parallel handling.

### 5. Support Files  
- `controller.csv`: Dual flag control for AI-Watcher handshake.  
- `ai-thought.csv`: Persistent log of AI trade ideas.  
- `transactionbook.csv`: Historical record of all trades.  
- `archive/<timestamp>/`: Automated backup of previous sessions.  
- `config.yaml`: Defines model paths, feature columns, thresholds, and fetch intervals.

---

## 🧠 AI & Strategy Layer

The AI component uses a **dual-model structure**:
- **Classifier Model** → Predicts probability of profitable short-term moves.  
- **Regressor Model** → Estimates expected magnitude of return.  

Feature inputs are dynamically generated from live candle data:
- Rolling mean & volatility
- Percent change & volume acceleration
- Price-level normalization

This two-layer inference allows the bot to both **filter noise** and **quantify conviction**, minimizing false positives during volatile market phases.

---

## 🔐 Privacy & Licensing

This system is **not open-source**.

- Core trading logic, dataset pipelines, and execution contracts are **intentionally redacted**.
- Redistribution, resale, or code reuse without written consent is **strictly prohibited**.
- You may study the architecture and request collaboration or API access via the author.

**License:**  
📄 **“Private Source License (Custom)”** —  
Usage, distribution, or modification of this software is only permitted with direct permission from the author.  
For inquiries, email: `contact.tblack@pm.me` or open a GitHub issue marked **Private Access Request**.

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|-------------|
| Core Runtime | Python 3.10+ |
| Data Fetching | Requests, YAML |
| AI Models | Scikit-learn (Joblib) |
| Orchestration | CSV Control System |
| API | GeckoTerminal, Dexscreener |
| Storage | Local CSV + Archive rotation |
| OS Support | Windows / Linux / Colab |

---

## 🧪 Run Structure (Development)

```bash
# 1. Reset and archive all CSVs
python main.py

# 2. System boot automatically:
#   - Runs get-pairs.py
#   - Starts DataLoop.py
#   - Waits for first sync
#   - Launches AI bot for 12-hour runtime

# 3. All CSV data and logs archived automatically in /archive
