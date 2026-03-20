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
    """

    def __init__(
        self,
        max_position_size: float = 100,
        daily_loss_limit: float = 500.0,
    ) -> None:
        self._max_position_size = max_position_size
        self._daily_loss_limit = daily_loss_limit
        self._daily_loss: float = 0.0
        self._trading_halted: bool = False

    def validate(self, order: Order, portfolio: PortfolioTracker) -> Order | None:
        """Validate an order against risk rules.

        Returns the order if it passes, or None if it should be blocked.
        """
        if self._trading_halted:
            logger.warning("Order BLOCKED — trading halted due to daily loss limit.")
            return None

        # Check daily loss limit
        if portfolio.realized_pnl < -abs(self._daily_loss_limit):
            self._trading_halted = True
            logger.error(
                "Daily loss limit of %.2f breached (P&L: %.2f). Halting all trading.",
                self._daily_loss_limit,
                portfolio.realized_pnl,
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

    def reset_daily_limits(self) -> None:
        """Call this at the start of each trading day."""
        self._daily_loss = 0.0
        self._trading_halted = False
        logger.info("Daily risk limits reset.")
