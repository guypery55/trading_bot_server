import logging
from broker.order_models import Fill, OrderSide, Position

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Tracks open positions and realized/unrealized P&L in memory.

    Updated on every fill received from the broker.
    """

    def __init__(self) -> None:
        # symbol -> {"quantity": float, "average_cost": float}
        self._positions: dict[str, dict] = {}
        self._realized_pnl: float = 0.0
        self._total_commission: float = 0.0

    def record_fill(self, fill: Fill) -> None:
        """Update internal position state based on a fill."""
        symbol = fill.symbol
        qty = fill.filled_quantity
        price = fill.average_price

        if symbol not in self._positions:
            self._positions[symbol] = {"quantity": 0.0, "average_cost": 0.0}

        pos = self._positions[symbol]

        if fill.side == OrderSide.BUY:
            # Update average cost via weighted average
            total_qty = pos["quantity"] + qty
            if total_qty > 0:
                pos["average_cost"] = (
                    pos["quantity"] * pos["average_cost"] + qty * price
                ) / total_qty
            pos["quantity"] = total_qty

        elif fill.side == OrderSide.SELL:
            # Realize P&L on the closed portion
            realized = (price - pos["average_cost"]) * qty
            self._realized_pnl += realized
            pos["quantity"] -= qty
            if pos["quantity"] <= 0:
                self._positions.pop(symbol, None)

        self._total_commission += fill.commission
        logger.debug(
            "Fill recorded: %s %s x %s @ %.4f | Realized P&L: %.2f",
            fill.side.value,
            qty,
            symbol,
            price,
            self._realized_pnl,
        )

    def get_position(self, symbol: str) -> Position | None:
        """Return current position for a symbol, or None if flat."""
        pos = self._positions.get(symbol)
        if pos is None or pos["quantity"] == 0:
            return None
        return Position(
            symbol=symbol,
            quantity=pos["quantity"],
            average_cost=pos["average_cost"],
        )

    def get_all_positions(self) -> list[Position]:
        return [
            Position(symbol=s, quantity=p["quantity"], average_cost=p["average_cost"])
            for s, p in self._positions.items()
            if p["quantity"] != 0
        ]

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def total_commission(self) -> float:
        return self._total_commission
