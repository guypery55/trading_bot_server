"""Shared pytest fixtures for the trading bot test suite."""

import pandas as pd
import pytest

from broker.base import BrokerInterface
from broker.order_models import AccountSummary, Fill, Order, OrderSide, Position


# ── Mock Broker ───────────────────────────────────────────────────────────────

class MockBroker(BrokerInterface):
    """In-memory broker for tests. Records placed orders, returns fake fills."""

    def __init__(self) -> None:
        self.placed_orders: list[Order] = []
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def place_order(self, order: Order) -> Fill:
        self.placed_orders.append(order)
        return Fill(
            order_id="mock-order-id",
            symbol=order.symbol,
            side=order.side,
            filled_quantity=order.quantity,
            average_price=150.0,
            commission=1.0,
        )

    async def cancel_order(self, order_id: str) -> None:
        pass

    async def get_positions(self) -> list[Position]:
        return []

    async def get_account_summary(self) -> AccountSummary:
        return AccountSummary(
            net_liquidation=100_000.0,
            buying_power=50_000.0,
            cash_balance=50_000.0,
        )

    @property
    def is_connected(self) -> bool:
        return self._connected


@pytest.fixture
def mock_broker() -> MockBroker:
    return MockBroker()


# ── Sample OHLCV DataFrames ───────────────────────────────────────────────────

def make_bars(n: int = 100, base_price: float = 150.0) -> pd.DataFrame:
    """Generate a simple synthetic OHLCV DataFrame with n bars."""
    import numpy as np

    rng = np.random.default_rng(42)
    closes = base_price + rng.normal(0, 1, n).cumsum()
    opens = closes + rng.normal(0, 0.2, n)
    highs = np.maximum(closes, opens) + rng.uniform(0, 0.5, n)
    lows = np.minimum(closes, opens) - rng.uniform(0, 0.5, n)
    volumes = rng.integers(10_000, 100_000, n).astype(float)

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


@pytest.fixture
def sample_bars() -> pd.DataFrame:
    return make_bars(100)


@pytest.fixture
def short_bars() -> pd.DataFrame:
    """Only 10 bars — too short for most indicators."""
    return make_bars(10)
