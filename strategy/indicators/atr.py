import pandas as pd


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range — measures volatility.

    True Range is the greatest of:
        1. Current high − current low
        2. |current high − previous close|
        3. |current low  − previous close|

    ATR is the smoothed (Wilder) moving average of the True Range.

    Args:
        high:   High price series.
        low:    Low price series.
        close:  Closing price series.
        period: Smoothing period (default 14).

    Returns:
        ATR series.
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder smoothing (equivalent to EMA with alpha = 1/period)
    return true_range.ewm(alpha=1 / period, min_periods=period).mean()
