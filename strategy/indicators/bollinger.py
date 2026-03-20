import pandas as pd
from .moving_average import sma


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Args:
        series: Closing price series.
        period: Rolling window period (default 20).
        num_std: Number of standard deviations for band width (default 2).

    Returns:
        Tuple of (upper_band, middle_band, lower_band).
    """
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + (std * num_std)
    lower = middle - (std * num_std)
    return upper, middle, lower
