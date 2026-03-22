import pandas as pd


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (RSI).

    Args:
        series: Closing price series.
        period: Lookback period (default 14).

    Returns:
        RSI values in range [0, 100].
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    # When avg_loss == 0: all gains, no losses → RSI = 100
    # Use NaN as intermediate to avoid 0/0 and then fill correctly
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    result = 100 - (100 / (1 + rs))
    result[avg_loss == 0] = 100.0
    return result
