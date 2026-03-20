from abc import ABC, abstractmethod
import pandas as pd
from broker.order_models import Order


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    Strategies are pure signal generators:
    - They receive OHLCV bar data.
    - They return a list of Order objects to submit.
    - They have NO access to the broker or any side effects.

    This makes strategies independently testable with synthetic DataFrames.
    """

    def __init__(self, symbol: str, params: dict) -> None:
        self.symbol = symbol
        self.params = params

    @abstractmethod
    def on_bar(self, bars: pd.DataFrame) -> list[Order]:
        """Called on each new completed bar.

        Args:
            bars: DataFrame with columns [open, high, low, close, volume],
                  sorted oldest → newest. Each row is one bar.

        Returns:
            A (possibly empty) list of Order objects to submit.
        """
        ...

    def on_start(self) -> None:
        """Called once before the main loop begins. Override for setup logic."""

    def on_stop(self) -> None:
        """Called once after the main loop ends. Override for cleanup logic."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(symbol={self.symbol}, params={self.params})"
