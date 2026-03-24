"""Trading Bot Server — Entry Point & Composition Root.

This is the only file that instantiates concrete classes and wires them together.
All other modules receive their dependencies via constructor injection.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from config import Settings, configure_logging, load_settings
from broker.ibkr_broker import IBKRBroker
from data.market_data import MarketDataFeed
from engine.risk_manager import RiskManager
from engine.trading_engine import TradingEngine
from portfolio.portfolio_tracker import PortfolioTracker
from strategy.base import BaseStrategy
from strategy.breakout_strategy import BreakoutStrategy
from strategy.rsi_macd_strategy import RSIMACDStrategy
from strategy.swing_strategy import SwingStrategy

# ── Strategy registry ──────────────────────────────────────────────────────────
# Add new strategies here — no other files need to change.
STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "rsi_macd": RSIMACDStrategy,
    "breakout": BreakoutStrategy,
    "swing": SwingStrategy,
}

logger = logging.getLogger(__name__)


def build_feeds(
    broker: IBKRBroker,
    settings: Settings,
) -> list[tuple[MarketDataFeed, BaseStrategy]]:
    """Create one (MarketDataFeed, Strategy) pair per symbol."""
    strategy_cls = STRATEGY_REGISTRY.get(settings.strategy)
    if strategy_cls is None:
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"Unknown strategy '{settings.strategy}'. Available: {available}"
        )

    feeds = []
    for symbol in settings.symbols:
        feed = MarketDataFeed(broker, symbol, settings.bar_size)
        strategy = strategy_cls(symbol=symbol)
        feeds.append((feed, strategy))

    return feeds


async def main() -> None:
    # ── Load config & logging ──────────────────────────────────────────────────
    settings = load_settings()
    configure_logging(settings.log_level)

    logger.info("=" * 60)
    logger.info("  Trading Bot Server")
    logger.info("  Mode      : %s", settings.trading_mode.value.upper())
    logger.info("  Strategy  : %s", settings.strategy)
    logger.info("  Symbols   : %d  (%s)", len(settings.symbols), ", ".join(settings.symbols[:5]) + ("..." if len(settings.symbols) > 5 else ""))
    logger.info("  Spend cap : $%.2f / day", settings.daily_spend_limit)
    logger.info("  Loss limit: $%.2f / day", settings.daily_loss_limit)
    logger.info("  IBKR      : %s:%s (clientId=%s)", settings.ibkr_host, settings.ibkr_port, settings.ibkr_client_id)
    logger.info("=" * 60)

    # ── Build dependencies ────────────────────────────────────────────────────
    broker = IBKRBroker(settings)
    feeds = build_feeds(broker, settings)
    risk_manager = RiskManager(
        daily_loss_limit=settings.daily_loss_limit,
        daily_spend_limit=settings.daily_spend_limit,
    )
    portfolio = PortfolioTracker()

    # Optional Telegram notifier
    notifier = None
    if settings.notifications_enabled:
        from notifications.telegram_notifier import TelegramNotifier
        notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)

    # ── Wire the engine ───────────────────────────────────────────────────────
    engine = TradingEngine(
        broker=broker,
        feeds=feeds,
        risk_manager=risk_manager,
        portfolio=portfolio,
        notifier=notifier,
    )

    # ── Signal handling (Ctrl+C / SIGTERM) ────────────────────────────────────
    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str) -> None:
        logger.info("Received %s — shutting down...", sig_name)
        loop.create_task(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    # ── Run ───────────────────────────────────────────────────────────────────
    try:
        await engine.run()
    except ConnectionRefusedError as exc:
        logger.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
