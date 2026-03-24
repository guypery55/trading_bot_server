import logging
import pandas as pd

from broker.order_models import Order, OrderSide, OrderType
from .base import BaseStrategy

logger = logging.getLogger(__name__)


class BreakoutStrategy(BaseStrategy):
    """N-bar range breakout strategy.

    Looks back `lookback_period` bars to find the highest high and lowest low.
    Enters a position when the latest close breaks out of that range.

    Entry rules:
        BUY  when close > N-bar high * (1 + breakout_buffer)
        SELL when close < N-bar low  * (1 - breakout_buffer)

    Default parameters:
        lookback_period  = 20    - Number of bars to define the range
        breakout_buffer  = 0.001 - 0.1% buffer above/below range to filter noise
        order_quantity   = 1
    """

    DEFAULT_PARAMS = {
        "lookback_period": 20,
        "breakout_buffer": 0.001,
        "order_quantity": 1,
    }

    def __init__(self, symbol: str, params: dict | None = None) -> None:
        merged = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(symbol, merged)

    def on_bar(self, bars: pd.DataFrame) -> list[Order]:
        lookback = self.params["lookback_period"]
        buffer = self.params["breakout_buffer"]

        # Need lookback + 1 bars: lookback for the range, +1 for the current bar
        if len(bars) < lookback + 1:
            logger.debug("Not enough bars (%s < %s), skipping.", len(bars), lookback + 1)
            return []

        # Define range using all bars EXCEPT the current one
        history = bars.iloc[-(lookback + 1):-1]
        current_close = bars["close"].iloc[-1]

        range_high = history["high"].max()
        range_low = history["low"].min()

        breakout_high = range_high * (1 + buffer)
        breakout_low = range_low * (1 - buffer)

        orders: list[Order] = []

        if current_close > breakout_high:
            logger.info(
                "BUY signal: close=%.4f broke above %s-bar high=%.4f (buffer=%.4f).",
                current_close,
                lookback,
                range_high,
                breakout_high,
            )
            orders.append(
                Order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    quantity=self.params["order_quantity"],
                    order_type=OrderType.MARKET,
                )
            )

        elif current_close < breakout_low:
            logger.info(
                "SELL signal: close=%.4f broke below %s-bar low=%.4f (buffer=%.4f).",
                current_close,
                lookback,
                range_low,
                breakout_low,
            )
            orders.append(
                Order(
                    symbol=self.symbol,
                    side=OrderSide.SELL,
                    quantity=self.params["order_quantity"],
                    order_type=OrderType.MARKET,
                )
            )

        return orders
