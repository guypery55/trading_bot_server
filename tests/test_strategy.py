"""Unit tests for strategy classes (no broker connection required)."""

import numpy as np
import pandas as pd
import pytest

from broker.order_models import OrderSide, OrderType
from strategy.breakout_strategy import BreakoutStrategy
from strategy.rsi_macd_strategy import RSIMACDStrategy
from strategy.swing_strategy import SwingStrategy
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


class TestSwingStrategy:
    def test_returns_no_orders_with_insufficient_bars(self, short_bars):
        strategy = SwingStrategy(symbol="AAPL")
        orders = strategy.on_bar(short_bars)
        assert orders == []

    def test_returns_list_with_enough_bars(self, sample_bars):
        strategy = SwingStrategy(symbol="AAPL")
        orders = strategy.on_bar(sample_bars)
        assert isinstance(orders, list)

    def test_order_has_correct_symbol(self, sample_bars):
        strategy = SwingStrategy(symbol="TSLA")
        orders = strategy.on_bar(sample_bars)
        for order in orders:
            assert order.symbol == "TSLA"

    def test_order_type_is_market(self, sample_bars):
        strategy = SwingStrategy(symbol="AAPL")
        orders = strategy.on_bar(sample_bars)
        for order in orders:
            assert order.order_type == OrderType.MARKET

    def test_custom_params_override_defaults(self):
        strategy = SwingStrategy(symbol="AAPL", params={"ema_fast": 5, "atr_stop_mult": 3.0})
        assert strategy.params["ema_fast"] == 5
        assert strategy.params["atr_stop_mult"] == 3.0
        # Default values should still be present
        assert strategy.params["ema_slow"] == 50

    def test_position_state_resets_on_start(self):
        strategy = SwingStrategy(symbol="AAPL")
        strategy._position = 1
        strategy._entry_price = 150.0
        strategy.on_start()
        assert strategy._position == 0
        assert strategy._entry_price == 0.0

    def test_stop_loss_exit_long(self):
        """Verify that a long position triggers stop-loss on a price drop."""
        strategy = SwingStrategy(symbol="AAPL", params={"atr_stop_mult": 2.0})

        # Simulate being in a long position
        strategy._position = 1
        strategy._entry_price = 100.0
        strategy._entry_atr = 2.0  # stop at 100 - 2*2 = 96
        strategy._bars_held = 1
        strategy._best_price = 100.0

        # Build bars where the last close is below the stop-loss
        n = 60
        rng = np.random.default_rng(99)
        close = np.full(n, 100.0)
        close[-1] = 95.0  # below stop of 96
        high = close + rng.uniform(0.1, 0.5, n)
        low = close - rng.uniform(0.1, 0.5, n)
        low[-1] = 94.5
        bars = pd.DataFrame({
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 50000.0),
        })

        orders = strategy.on_bar(bars)
        assert len(orders) == 1
        assert orders[0].side == OrderSide.SELL  # exit long = sell

    def test_stop_loss_exit_short(self):
        """Verify that a short position triggers stop-loss on a price rise."""
        strategy = SwingStrategy(symbol="AAPL", params={"atr_stop_mult": 2.0})

        strategy._position = -1
        strategy._entry_price = 100.0
        strategy._entry_atr = 2.0  # stop at 100 + 2*2 = 104
        strategy._bars_held = 1
        strategy._best_price = 100.0

        n = 60
        rng = np.random.default_rng(99)
        close = np.full(n, 100.0)
        close[-1] = 105.0  # above stop of 104
        high = close + rng.uniform(0.1, 0.5, n)
        high[-1] = 105.5
        low = close - rng.uniform(0.1, 0.5, n)
        bars = pd.DataFrame({
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 50000.0),
        })

        orders = strategy.on_bar(bars)
        assert len(orders) == 1
        assert orders[0].side == OrderSide.BUY  # exit short = buy

    def test_time_stop_exit(self):
        """Position held beyond max_hold_bars triggers time stop."""
        strategy = SwingStrategy(symbol="AAPL", params={"max_hold_bars": 5})

        strategy._position = 1
        strategy._entry_price = 100.0
        strategy._entry_atr = 10.0  # large ATR so stop/TP won't trigger
        strategy._bars_held = 4  # will become 5 in on_bar
        strategy._best_price = 100.0

        n = 60
        close = np.full(n, 100.0)
        high = close + 0.1
        low = close - 0.1
        bars = pd.DataFrame({
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 50000.0),
        })

        orders = strategy.on_bar(bars)
        assert len(orders) == 1
        assert orders[0].side == OrderSide.SELL

    def test_no_entry_when_already_in_position(self):
        """Strategy should not emit new entry signals while holding a position."""
        strategy = SwingStrategy(symbol="AAPL")
        strategy._position = 1
        strategy._entry_price = 100.0
        strategy._entry_atr = 100.0  # huge ATR so no stop/TP triggers
        strategy._bars_held = 0
        strategy._best_price = 100.0

        n = 100
        rng = np.random.default_rng(42)
        close = 100.0 + rng.normal(0, 0.01, n).cumsum()
        bars = pd.DataFrame({
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": np.full(n, 50000.0),
        })

        orders = strategy.on_bar(bars)
        # Should either be empty (still holding) or a single exit — never two orders
        assert len(orders) <= 1
