# Trading Bot Server

An automated trading bot for Interactive Brokers (IBKR) built in Python. Supports technical analysis strategies with paper and live trading modes.

## Features

- **IBKR connectivity** via `ib_insync` (TWS and IB Gateway)
- **Paper trading** via IBKR's built-in paper account (port 7497)
- **Two strategies out of the box**: RSI+MACD and Breakout
- **Risk management**: max position size, daily loss limit
- **Trade logging** to SQLite
- **Telegram notifications** (optional)
- **Fully testable** — strategies and risk logic work without a live IBKR connection

## Requirements

- Python 3.11+
- IBKR account with TWS or IB Gateway running locally
- API connections enabled in TWS/Gateway settings

## Setup

1. **Clone and install dependencies:**
   ```bash
   git clone <repo-url>
   cd trading_bot_server
   pip install -r requirements.txt
   ```

2. **Copy and configure your environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` with your settings (see [Configuration](#configuration) below).

3. **Enable API access in TWS / IB Gateway:**
   - TWS: *Edit → Global Configuration → API → Settings*
   - Check **Enable ActiveX and Socket Clients**
   - Make sure the port matches your `TRADING_MODE`

4. **Run the bot:**
   ```bash
   python main.py
   ```

## Configuration

| Variable | Description | Default |
|---|---|---|
| `IBKR_HOST` | Host where TWS/Gateway is running | `127.0.0.1` |
| `IBKR_CONNECTION_TYPE` | `tws` or `gateway` | `tws` |
| `IBKR_PORT` | Override port (auto-derived if omitted) | auto |
| `IBKR_CLIENT_ID` | Unique client ID per connected script | `1` |
| `TRADING_MODE` | `paper` or `live` | `paper` |
| `SYMBOL` | Trading symbol (e.g. `AAPL`, `SPY`) | `AAPL` |
| `BAR_SIZE` | IBKR bar size string | `5 mins` |
| `STRATEGY` | `rsi_macd` or `breakout` | `rsi_macd` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `DATABASE_URL` | SQLite path for trade logs | `sqlite:///./trades.db` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token (optional) | — |
| `TELEGRAM_CHAT_ID` | Telegram chat ID (optional) | — |

### Default IBKR ports

| Mode | TWS | IB Gateway |
|---|---|---|
| Paper | 7497 | 4002 |
| Live | 7496 | 4001 |

## Strategies

### `rsi_macd` — RSI + MACD Confluence
Combines two indicators to reduce false signals:
- **BUY** when RSI < 30 (oversold) AND MACD line crosses above signal line
- **SELL** when RSI > 70 (overbought) AND MACD line crosses below signal line

### `breakout` — N-Bar Range Breakout
Identifies consolidation ranges and trades the breakout:
- **BUY** when close breaks above the 20-bar high (+ 0.1% buffer)
- **SELL** when close breaks below the 20-bar low (- 0.1% buffer)

## Project Structure

```
trading_bot_server/
├── main.py              # Entry point & composition root
├── config/              # Settings (Pydantic BaseSettings) + logging
├── broker/              # BrokerInterface ABC + IBKRBroker implementation
├── strategy/            # BaseStrategy + RSI/MACD + Breakout + indicators/
├── engine/              # TradingEngine + RiskManager
├── data/                # MarketDataFeed (historical + real-time bars)
├── portfolio/           # PortfolioTracker (in-memory positions + P&L)
├── storage/             # TradeLogger (SQLite via aiosqlite)
├── tests/               # pytest tests (no IBKR connection needed)
└── logs/                # Runtime log files (gitignored)
```

## Running Tests

```bash
pytest tests/ -v
```

All tests run without a live IBKR connection using mock brokers and synthetic data.

## Adding a New Strategy

1. Create `strategy/my_strategy.py` extending `BaseStrategy`
2. Implement `on_bar(bars: pd.DataFrame) -> list[Order]`
3. Add one line to `STRATEGY_REGISTRY` in `main.py`
4. Set `STRATEGY=my_strategy` in `.env`

## Warning

Always test in **paper mode** before switching to live trading. This software is provided as-is with no guarantees. Trading involves significant financial risk.
