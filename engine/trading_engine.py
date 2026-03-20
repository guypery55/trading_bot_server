import asyncio
import logging

import pandas as pd

from broker.base import BrokerInterface
from data.market_data import MarketDataFeed
from portfolio.portfolio_tracker import PortfolioTracker
from strategy.base import BaseStrategy
from .risk_manager import RiskManager

logger = logging.getLogger(__name__)


class TradingEngine:
    """Orchestrates the trading loop.

    Wires together: broker, strategy, risk manager, market data, portfolio,
    and optional notifications. All dependencies are injected —
    no globals, no singletons.

    Flow on each new bar:
        market_data → strategy.on_bar() → risk_manager.validate()
        → broker.place_order() → portfolio.record_fill()
        → notifier.send_fill_alert()
    """

    def __init__(
        self,
        broker: BrokerInterface,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        market_data: MarketDataFeed,
        portfolio: PortfolioTracker,
        notifier=None,          # Optional notifier (e.g. TelegramNotifier)
    ) -> None:
        self._broker = broker
        self._strategy = strategy
        self._risk = risk_manager
        self._market_data = market_data
        self._portfolio = portfolio
        self._notifier = notifier
        self._running = False

    async def run(self) -> None:
        """Main entry point. Connects broker, loads history, starts streaming."""
        logger.info("Trading engine starting — strategy: %s", self._strategy)
        self._running = True

        await self._broker.connect()
        self._strategy.on_start()

        # Load historical bars to warm up indicators
        await self._market_data.load_history(lookback_days=60)

        # Register bar callback and start streaming
        self._market_data.subscribe(self._on_new_bar)
        await self._market_data.start_streaming()

        logger.info("Engine running. Waiting for bars...")

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully shut down the engine."""
        logger.info("Shutting down trading engine...")
        self._running = False
        self._strategy.on_stop()
        await self._market_data.stop_streaming()
        await self._broker.disconnect()
        logger.info("Engine stopped.")

    async def _on_new_bar(self, bars: pd.DataFrame) -> None:
        """Called on every new completed bar. Core trading loop."""
        orders = self._strategy.on_bar(bars)

        for order in orders:
            validated = self._risk.validate(order, self._portfolio)
            if validated is None:
                continue

            try:
                fill = await self._broker.place_order(validated)
            except Exception as exc:
                logger.error("Order placement failed for %s: %s", order.symbol, exc)
                continue

            self._portfolio.record_fill(fill)

            if self._notifier:
                try:
                    await self._notifier.send_fill_alert(fill)
                except Exception as exc:
                    logger.warning("Notification failed: %s", exc)
