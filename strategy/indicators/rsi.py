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

    rs = avg_gain / avg_loss.replace(0, float("inf"))
    return 100 - (100 / (1 + rs))
