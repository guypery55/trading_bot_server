# Trading Bot Server

An automated trading bot for Interactive Brokers (IBKR) built in Python. Supports technical analysis strategies with paper and live trading modes.

## Features

- **IBKR connectivity** via `ib_insync` (TWS and IB Gateway)
- **Paper trading** via IBKR's built-in paper account (port 7497)
- **Three strategies out of the box**: RSI+MACD, Breakout, and Swing
- **Risk management**: max position size, daily loss limit, ATR-based stops
- **Telegram notifications** — trade fill alerts + log forwarding (INFO/ERROR/CRITICAL)
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
| `STRATEGY` | `rsi_macd`, `breakout`, or `swing` | `rsi_macd` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
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

### `swing` — Multi-Signal Confluence Swing Trading
Holds positions for days to weeks. Enters only when **5 independent signals** align:
1. **Trend filter** — price above/below 50 EMA
2. **Momentum shift** — 9 EMA crosses 21 EMA
3. **RSI sweet spot** — RSI between 40–60 (not overbought/oversold)
4. **Volume surge** — volume > 120% of 20-bar average
5. **MACD acceleration** — histogram positive & increasing

Exit conditions:
- **ATR stop-loss** (2× ATR) and **take-profit** (3× ATR, 1.5:1 R:R)
- **Trailing stop** activates after 1.5× ATR profit
- **Trend invalidation** if price crosses back through 50 EMA
- **Time stop** after max hold period

## Telegram Notifications

When `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`, the bot will:
- Send **trade fill alerts** (buy/sell, price, quantity, commission)
- Forward **INFO, ERROR, and CRITICAL** log messages to your Telegram chat

To set up a Telegram bot:
1. Message **@BotFather** on Telegram → `/newbot`
2. Copy the bot token into `.env`
3. Send any message to your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID

## Project Structure

```
trading_bot_server/
├── main.py              # Entry point & composition root
├── config/              # Settings (Pydantic BaseSettings) + logging
├── broker/              # BrokerInterface ABC + IBKRBroker implementation
├── strategy/            # BaseStrategy + RSI/MACD + Breakout + Swing + indicators/
├── engine/              # TradingEngine + RiskManager
├── data/                # MarketDataFeed (historical + real-time bars)
├── portfolio/           # PortfolioTracker (in-memory positions + P&L)
├── notifications/       # TelegramNotifier (async trade alerts)
├── utils/               # Sync Telegram helper for logging handler
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
