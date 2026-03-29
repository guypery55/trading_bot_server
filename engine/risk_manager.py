from __future__ import annotations

import logging
from broker.order_models import Order, OrderSide
from portfolio.portfolio_tracker import PortfolioTracker

logger = logging.getLogger(__name__)


class RiskManager:
    """Guards order flow with configurable risk limits.

    Checks performed before every order:
    1. Daily spend limit  — total $ value traded today across all symbols.
    2. Daily loss limit   — halts trading if today's P&L drops below threshold.
    3. Max position size  — prevents over-concentration in one symbol.

    Call reset_daily_limits() at the start of each trading day.
    """

    def __init__(
        self,
        max_position_size: float = 100,
        daily_loss_limit: float = 500.0,
        daily_spend_limit: float = 1000.0,
    ) -> None:
        self._max_position_size = max_position_size
        self._daily_loss_limit = daily_loss_limit
        self._daily_spend_limit = daily_spend_limit

        self._pnl_at_day_start: float = 0.0
        self._daily_spent: float = 0.0      # cumulative $ value of orders today
        self._trading_halted: bool = False

    def validate(
        self,
        order: Order,
        portfolio: PortfolioTracker,
        current_price: float = 0.0,
    ) -> Order | None:
        """Validate an order against all risk rules.

        Args:
            order:         The order to evaluate.
            portfolio:     Current portfolio state for P&L and position checks.
            current_price: Last known price of the symbol (used to estimate
                           order value for the daily spend limit).

        Returns the order unchanged if it passes, or None if it is blocked.
        """
        if self._trading_halted:
            logger.warning("Order BLOCKED — trading halted (daily limit reached).")
            return None

        # ── 1. Daily loss limit ───────────────────────────────────────────────
        daily_pnl = portfolio.realized_pnl - self._pnl_at_day_start
        if daily_pnl < -abs(self._daily_loss_limit):
            self._trading_halted = True
            logger.error(
                "Daily loss limit of $%.2f breached (today P&L: $%.2f). Halting trading.",
                self._daily_loss_limit,
                daily_pnl,
            )
            return None

        # ── 2. Daily spend limit ──────────────────────────────────────────────
        if current_price > 0:
            estimated_value = order.quantity * current_price
            if self._daily_spent + estimated_value > self._daily_spend_limit:
                logger.warning(
                    "Order BLOCKED — daily spend limit of $%.2f reached "
                    "(spent so far: $%.2f, this order: ~$%.2f).",
                    self._daily_spend_limit,
                    self._daily_spent,
                    estimated_value,
                )
                return None
            self._daily_spent += estimated_value
            logger.debug(
                "Daily spend: $%.2f / $%.2f after %s %s x%.0f @ ~$%.2f",
                self._daily_spent,
                self._daily_spend_limit,
                order.side.value,
                order.symbol,
                order.quantity,
                current_price,
            )

        # ── 3. Max position size ──────────────────────────────────────────────
        existing = portfolio.get_position(order.symbol)
        if existing:
            new_qty = existing.quantity + (
                order.quantity if order.side == OrderSide.BUY else -order.quantity
            )
            if abs(new_qty) > self._max_position_size:
                logger.warning(
                    "Order BLOCKED — would exceed max position size of %s "
                    "(current: %s, order: %s).",
                    self._max_position_size,
                    existing.quantity,
                    order.quantity,
                )
                return None

        return order

    def reset_daily_limits(self, portfolio: PortfolioTracker) -> None:
        """Call at the start of each trading day to reset all daily counters."""
        self._pnl_at_day_start = portfolio.realized_pnl
        self._daily_spent = 0.0
        self._trading_halted = False
        logger.info(
            "Daily risk limits reset — P&L baseline: $%.2f | spend limit: $%.2f",
            self._pnl_at_day_start,
            self._daily_spend_limit,
        )

    @property
    def daily_spent(self) -> float:
        return self._daily_spent

    @property
    def daily_spend_remaining(self) -> float:
        return max(0.0, self._daily_spend_limit - self._daily_spent)
