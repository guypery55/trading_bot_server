# Trading Bot Server

An automated trading bot server supporting multiple exchanges with paper and live trading modes.

## Features

- Multi-exchange support (Binance, Bybit, Kraken, Coinbase)
- Paper trading mode for safe strategy testing
- REST API server for bot management
- Configurable trading strategies
- Telegram notifications
- Trade logging and history

## Setup

1. Clone the repository:
   ```bash
   git clone <repo-url>
   cd trading_bot_server
   ```

2. Copy the example env file and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

3. Set your API keys and configuration in `.env`.

## Configuration

| Variable | Description | Default |
|---|---|---|
| `EXCHANGE` | Exchange to connect to | `binance` |
| `API_KEY` | Exchange API key | — |
| `API_SECRET` | Exchange API secret | — |
| `TRADING_MODE` | `paper` or `live` | `paper` |
| `BASE_CURRENCY` | Quote currency for trading pairs | `USDT` |
| `PORT` | Server port | `8000` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## Usage

> Setup instructions will be added as the project develops.

## Warning

Always test strategies in **paper mode** before switching to live trading. Trading involves significant financial risk.
