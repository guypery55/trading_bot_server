"""Unit tests for the RiskManager."""

import pytest

from broker.order_models import Fill, Order, OrderSide, OrderType
from engine.risk_manager import RiskManager
from portfolio.portfolio_tracker import PortfolioTracker


def make_order(side: OrderSide = OrderSide.BUY, quantity: float = 1.0) -> Order:
    return Order(symbol="AAPL", side=side, quantity=quantity, order_type=OrderType.MARKET)


def make_fill(side: OrderSide, quantity: float, price: float) -> Fill:
    return Fill(
        order_id="test",
        symbol="AAPL",
        side=side,
        filled_quantity=quantity,
        average_price=price,
        commission=0.0,
    )


class TestRiskManager:
    def test_valid_order_passes_through(self):
        rm = RiskManager()
        portfolio = PortfolioTracker()
        order = make_order()
        result = rm.validate(order, portfolio)
        assert result is order

    def test_blocks_when_trading_halted(self):
        rm = RiskManager(daily_loss_limit=100.0)
        portfolio = PortfolioTracker()
        # Simulate a large realized loss
        portfolio.record_fill(make_fill(OrderSide.BUY, 10, 200.0))
        portfolio.record_fill(make_fill(OrderSide.SELL, 10, 180.0))  # -200 loss
        order = make_order()
        result = rm.validate(order, portfolio)
        assert result is None

    def test_blocks_when_max_position_exceeded(self):
        rm = RiskManager(max_position_size=5)
        portfolio = PortfolioTracker()
        # Already holding 4 shares
        portfolio.record_fill(make_fill(OrderSide.BUY, 4, 100.0))
        # Trying to buy 2 more would make 6 > max of 5
        order = make_order(side=OrderSide.BUY, quantity=2)
        result = rm.validate(order, portfolio)
        assert result is None

    def test_allows_order_within_position_limit(self):
        rm = RiskManager(max_position_size=10)
        portfolio = PortfolioTracker()
        portfolio.record_fill(make_fill(OrderSide.BUY, 4, 100.0))
        # Buying 5 more = 9, which is within max of 10
        order = make_order(side=OrderSide.BUY, quantity=5)
        result = rm.validate(order, portfolio)
        assert result is order

    def test_reset_daily_limits_allows_trading_again(self):
        rm = RiskManager(daily_loss_limit=100.0)
        portfolio = PortfolioTracker()
        portfolio.record_fill(make_fill(OrderSide.BUY, 10, 200.0))
        portfolio.record_fill(make_fill(OrderSide.SELL, 10, 180.0))

        # First validate — should be halted
        assert rm.validate(make_order(), portfolio) is None

        # Reset — should pass again
        rm.reset_daily_limits()
        assert rm.validate(make_order(), portfolio) is not None
