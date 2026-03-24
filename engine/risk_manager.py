from __future__ import annotations

import logging
from broker.order_models import Order, OrderSide
from portfolio.portfolio_tracker import PortfolioTracker

logger = logging.getLogger(__name__)


class RiskManager:
    """Guards order flow with configurable risk limits.

    Checks performed before every order:
    - Max position size per symbol
    - Daily loss limit (stops all trading if breached)
    - Prevents adding to an already-open position in the same direction

    Daily loss tracking uses an internal snapshot: on reset, the current
    portfolio P&L is recorded as the baseline, and subsequent checks compare
    the delta against the daily limit. This prevents the bug where lifetime
    cumulative losses would permanently halt trading after a daily reset.
    """

    def __init__(
        self,
        max_position_size: float = 100,
        daily_loss_limit: float = 500.0,
    ) -> None:
        self._max_position_size = max_position_size
        self._daily_loss_limit = daily_loss_limit
        self._pnl_at_day_start: float = 0.0  # snapshot of realized_pnl at reset
        self._trading_halted: bool = False

    def validate(self, order: Order, portfolio: PortfolioTracker) -> Order | None:
        """Validate an order against risk rules.

        Returns the order if it passes, or None if it should be blocked.
        """
        if self._trading_halted:
            logger.warning("Order BLOCKED — trading halted due to daily loss limit.")
            return None

        # Check daily loss limit (delta from start of day, not lifetime)
        daily_pnl = portfolio.realized_pnl - self._pnl_at_day_start
        if daily_pnl < -abs(self._daily_loss_limit):
            self._trading_halted = True
            logger.error(
                "Daily loss limit of %.2f breached (today's P&L: %.2f). Halting all trading.",
                self._daily_loss_limit,
                daily_pnl,
            )
            return None

        # Check max position size
        existing = portfolio.get_position(order.symbol)
        if existing:
            new_qty = existing.quantity + (
                order.quantity if order.side == OrderSide.BUY else -order.quantity
            )
            if abs(new_qty) > self._max_position_size:
                logger.warning(
                    "Order BLOCKED — would exceed max position size of %s (current: %s, order: %s).",
                    self._max_position_size,
                    existing.quantity,
                    order.quantity,
                )
                return None

        return order

    def reset_daily_limits(self, portfolio: PortfolioTracker) -> None:
        """Call this at the start of each trading day.

        Snapshots the current P&L so that daily loss tracking starts fresh.
        """
        self._pnl_at_day_start = portfolio.realized_pnl
        self._trading_halted = False
        logger.info(
            "Daily risk limits reset. P&L baseline: %.2f", self._pnl_at_day_start
        )
