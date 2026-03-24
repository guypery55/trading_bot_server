from __future__ import annotations

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
    """Orchestrates the trading loop across multiple symbols in parallel.

    Each symbol gets its own (MarketDataFeed, BaseStrategy) pair. All symbols
    share a single broker, portfolio, and risk manager so that daily limits
    are enforced globally, not per-symbol.

    Flow on each new bar (per symbol):
        market_data → strategy.on_bar() → risk_manager.validate()
        → broker.place_order() → portfolio.record_fill()
        → notifier.send_fill_alert()
    """

    def __init__(
        self,
        broker: BrokerInterface,
        feeds: list[tuple[MarketDataFeed, BaseStrategy]],
        risk_manager: RiskManager,
        portfolio: PortfolioTracker,
        notifier=None,
    ) -> None:
        self._broker = broker
        self._feeds = feeds          # [(feed, strategy), ...]
        self._risk = risk_manager
        self._portfolio = portfolio
        self._notifier = notifier
        self._running = False

    async def run(self) -> None:
        """Connect broker, warm up all feeds, then stream bars from all symbols."""
        symbols = [s.symbol for _, s in self._feeds]
        logger.info(
            "Trading engine starting — %d symbol(s): %s",
            len(symbols),
            ", ".join(symbols),
        )
        self._running = True

        await self._broker.connect()

        for feed, strategy in self._feeds:
            strategy.on_start()

        # Load history for all symbols concurrently
        await asyncio.gather(*[
            feed.load_history(lookback_days=60)
            for feed, _ in self._feeds
        ])

        # Subscribe bar handlers and start streaming — stagger slightly to
        # avoid hitting IBKR's historical data pacing limits (50 req/10 s).
        for i, (feed, strategy) in enumerate(self._feeds):
            feed.subscribe(self._make_bar_handler(strategy))
            await feed.start_streaming()
            if i < len(self._feeds) - 1:
                await asyncio.sleep(0.25)   # ~4 streams/sec → safe under limits

        logger.info("Engine running. Streaming bars for %d symbol(s).", len(self._feeds))

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Gracefully shut down all feeds and the broker."""
        logger.info("Shutting down trading engine...")
        self._running = False

        for _, strategy in self._feeds:
            strategy.on_stop()

        await asyncio.gather(*[
            feed.stop_streaming() for feed, _ in self._feeds
        ])

        await self._broker.disconnect()
        logger.info("Engine stopped.")

    # ── internals ──────────────────────────────────────────────────────────────

    def _make_bar_handler(self, strategy: BaseStrategy):
        """Return a bar callback bound to a specific strategy instance."""

        async def _on_new_bar(bars: pd.DataFrame) -> None:
            if not self._running:
                return

            orders = strategy.on_bar(bars)
            current_price = float(bars["close"].iloc[-1]) if not bars.empty else 0.0

            for order in orders:
                validated = self._risk.validate(order, self._portfolio, current_price)
                if validated is None:
                    continue

                try:
                    fill = await self._broker.place_order(validated)
                except Exception as exc:
                    logger.error(
                        "Order placement failed for %s: %s", order.symbol, exc
                    )
                    continue

                self._portfolio.record_fill(fill)

                if self._notifier:
                    try:
                        await self._notifier.send_fill_alert(fill)
                    except Exception as exc:
                        logger.warning("Notification failed: %s", exc)

        return _on_new_bar
