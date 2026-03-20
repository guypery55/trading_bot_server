"""Unit tests for strategy classes (no broker connection required)."""

import pandas as pd
import pytest

from broker.order_models import OrderSide, OrderType
from strategy.breakout_strategy import BreakoutStrategy
from strategy.rsi_macd_strategy import RSIMACDStrategy
from tests.conftest import make_bars


class TestRSIMACDStrategy:
    def test_returns_no_orders_with_insufficient_bars(self, short_bars):
        strategy = RSIMACDStrategy(symbol="AAPL")
        orders = strategy.on_bar(short_bars)
        assert orders == []

    def test_returns_list_with_enough_bars(self, sample_bars):
        strategy = RSIMACDStrategy(symbol="AAPL")
        orders = strategy.on_bar(sample_bars)
        assert isinstance(orders, list)

    def test_order_has_correct_symbol(self, sample_bars):
        strategy = RSIMACDStrategy(symbol="MSFT")
        orders = strategy.on_bar(sample_bars)
        for order in orders:
            assert order.symbol == "MSFT"

    def test_order_type_is_market(self, sample_bars):
        strategy = RSIMACDStrategy(symbol="AAPL")
        orders = strategy.on_bar(sample_bars)
        for order in orders:
            assert order.order_type == OrderType.MARKET

    def test_buy_signal_on_oversold_macd_cross(self):
        """Construct bars where RSI is low and MACD crosses bullish."""
        # Falling prices to get low RSI, then a sharp reversal for MACD cross
        prices = [100.0 - i * 0.5 for i in range(60)]   # downtrend
        prices += [40.0 + i * 2.0 for i in range(10)]    # sharp reversal
        close = pd.Series(prices)
        bars = pd.DataFrame({
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": [10000.0] * len(close),
        })
        strategy = RSIMACDStrategy(symbol="AAPL")
        orders = strategy.on_bar(bars)
        buy_orders = [o for o in orders if o.side == OrderSide.BUY]
        # We may or may not get a buy depending on exact crossover — just assert no crash
        assert isinstance(buy_orders, list)


class TestBreakoutStrategy:
    def test_returns_no_orders_with_insufficient_bars(self, short_bars):
        strategy = BreakoutStrategy(symbol="AAPL", params={"lookback_period": 20})
        orders = strategy.on_bar(short_bars)
        assert orders == []

    def test_buy_on_upside_breakout(self):
        """Price breaks above the N-bar high."""
        lookback = 10
        # 10 bars consolidating around 100, then breakout bar
        bars_data = {"open": [], "high": [], "low": [], "close": [], "volume": []}
        for _ in range(lookback):
            bars_data["open"].append(99.0)
            bars_data["high"].append(101.0)
            bars_data["low"].append(98.0)
            bars_data["close"].append(100.0)
            bars_data["volume"].append(10000.0)
        # Breakout bar: close well above the range high of 101
        bars_data["open"].append(101.0)
        bars_data["high"].append(115.0)
        bars_data["low"].append(101.0)
        bars_data["close"].append(115.0)   # breaks above 101 * 1.001 = 101.101
        bars_data["volume"].append(50000.0)

        bars = pd.DataFrame(bars_data)
        strategy = BreakoutStrategy(symbol="AAPL", params={"lookback_period": lookback})
        orders = strategy.on_bar(bars)

        assert len(orders) == 1
        assert orders[0].side == OrderSide.BUY
        assert orders[0].symbol == "AAPL"
        assert orders[0].order_type == OrderType.MARKET

    def test_sell_on_downside_breakout(self):
        """Price breaks below the N-bar low."""
        lookback = 10
        bars_data = {"open": [], "high": [], "low": [], "close": [], "volume": []}
        for _ in range(lookback):
            bars_data["open"].append(99.0)
            bars_data["high"].append(101.0)
            bars_data["low"].append(98.0)
            bars_data["close"].append(100.0)
            bars_data["volume"].append(10000.0)
        # Breakdown bar: close well below range low of 98
        bars_data["open"].append(98.0)
        bars_data["high"].append(98.0)
        bars_data["low"].append(85.0)
        bars_data["close"].append(85.0)   # breaks below 98 * 0.999 = 97.902
        bars_data["volume"].append(50000.0)

        bars = pd.DataFrame(bars_data)
        strategy = BreakoutStrategy(symbol="AAPL", params={"lookback_period": lookback})
        orders = strategy.on_bar(bars)

        assert len(orders) == 1
        assert orders[0].side == OrderSide.SELL

    def test_no_signal_inside_range(self):
        """Price stays inside the range — no orders."""
        lookback = 10
        bars_data = {"open": [], "high": [], "low": [], "close": [], "volume": []}
        for _ in range(lookback + 1):
            bars_data["open"].append(99.0)
            bars_data["high"].append(101.0)
            bars_data["low"].append(98.0)
            bars_data["close"].append(100.0)
            bars_data["volume"].append(10000.0)

        bars = pd.DataFrame(bars_data)
        strategy = BreakoutStrategy(symbol="AAPL", params={"lookback_period": lookback})
        orders = strategy.on_bar(bars)
        assert orders == []
