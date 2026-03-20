"""Unit tests for all technical indicator functions."""

import pandas as pd
import pytest

from strategy.indicators import bollinger_bands, ema, macd, rsi, sma


@pytest.fixture
def price_series() -> pd.Series:
    """Simple ascending price series for deterministic testing."""
    return pd.Series([float(i) for i in range(1, 101)])  # 1 to 100


class TestSMA:
    def test_length(self, price_series):
        result = sma(price_series, period=10)
        assert len(result) == len(price_series)

    def test_first_valid_value(self, price_series):
        result = sma(price_series, period=10)
        # First 9 values should be NaN, 10th should be mean of 1..10 = 5.5
        assert pd.isna(result.iloc[8])
        assert result.iloc[9] == pytest.approx(5.5)

    def test_last_value(self, price_series):
        result = sma(price_series, period=10)
        # Last value = mean of 91..100 = 95.5
        assert result.iloc[-1] == pytest.approx(95.5)


class TestEMA:
    def test_length(self, price_series):
        result = ema(price_series, period=10)
        assert len(result) == len(price_series)

    def test_no_nan_after_period(self, price_series):
        result = ema(price_series, period=5)
        assert not result.iloc[5:].isna().any()

    def test_ema_lags_behind_rising_price(self, price_series):
        result = ema(price_series, period=10)
        # EMA should be below the current price in a rising series (lagging)
        assert result.iloc[-1] < price_series.iloc[-1]


class TestRSI:
    def test_range(self, price_series):
        result = rsi(price_series, period=14)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_length(self, price_series):
        result = rsi(price_series, period=14)
        assert len(result) == len(price_series)

    def test_trending_up_gives_high_rsi(self):
        """Monotonically rising prices should yield RSI near 100."""
        series = pd.Series([float(i) for i in range(1, 51)])
        result = rsi(series, period=14)
        assert result.iloc[-1] > 70

    def test_trending_down_gives_low_rsi(self):
        """Monotonically falling prices should yield RSI near 0."""
        series = pd.Series([float(i) for i in range(50, 0, -1)])
        result = rsi(series, period=14)
        assert result.iloc[-1] < 30


class TestMACD:
    def test_returns_three_series(self, price_series):
        macd_line, signal_line, histogram = macd(price_series)
        assert isinstance(macd_line, pd.Series)
        assert isinstance(signal_line, pd.Series)
        assert isinstance(histogram, pd.Series)

    def test_histogram_is_difference(self, price_series):
        macd_line, signal_line, histogram = macd(price_series)
        expected = macd_line - signal_line
        pd.testing.assert_series_equal(histogram, expected)

    def test_length(self, price_series):
        macd_line, signal_line, histogram = macd(price_series)
        assert len(macd_line) == len(price_series)


class TestBollingerBands:
    def test_returns_three_series(self, price_series):
        upper, middle, lower = bollinger_bands(price_series)
        assert isinstance(upper, pd.Series)
        assert isinstance(middle, pd.Series)
        assert isinstance(lower, pd.Series)

    def test_upper_above_lower(self, price_series):
        upper, _, lower = bollinger_bands(price_series)
        valid = upper.dropna()
        assert (valid > lower.dropna()).all()

    def test_middle_between_bands(self, price_series):
        upper, middle, lower = bollinger_bands(price_series)
        valid_idx = middle.dropna().index
        assert (middle[valid_idx] <= upper[valid_idx]).all()
        assert (middle[valid_idx] >= lower[valid_idx]).all()
