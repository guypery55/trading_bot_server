import logging
import pandas as pd

from broker.order_models import Order, OrderSide, OrderType
from .base import BaseStrategy
from .indicators import macd, rsi

logger = logging.getLogger(__name__)


class RSIMACDStrategy(BaseStrategy):
    """RSI + MACD confluence strategy.

    Entry rules:
        BUY  when RSI < oversold_threshold AND MACD line crosses above signal line.
        SELL when RSI > overbought_threshold AND MACD line crosses below signal line.

    Default parameters:
        rsi_period          = 14
        oversold_threshold  = 30
        overbought_threshold= 70
        macd_fast           = 12
        macd_slow           = 26
        macd_signal         = 9
        order_quantity      = 1
    """

    DEFAULT_PARAMS = {
        "rsi_period": 14,
        "oversold_threshold": 30,
        "overbought_threshold": 70,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "order_quantity": 1,
    }

    def __init__(self, symbol: str, params: dict | None = None) -> None:
        merged = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(symbol, merged)

    def on_bar(self, bars: pd.DataFrame) -> list[Order]:
        min_bars = self.params["macd_slow"] + self.params["macd_signal"]
        if len(bars) < min_bars:
            logger.debug("Not enough bars (%s < %s), skipping.", len(bars), min_bars)
            return []

        close = bars["close"]

        # Compute indicators
        rsi_values = rsi(close, period=self.params["rsi_period"])
        macd_line, signal_line, _ = macd(
            close,
            fast=self.params["macd_fast"],
            slow=self.params["macd_slow"],
            signal=self.params["macd_signal"],
        )

        current_rsi = rsi_values.iloc[-1]
        # Detect crossover: previous bar had macd < signal, current bar has macd > signal
        macd_crossed_above = (
            macd_line.iloc[-2] < signal_line.iloc[-2]
            and macd_line.iloc[-1] > signal_line.iloc[-1]
        )
        macd_crossed_below = (
            macd_line.iloc[-2] > signal_line.iloc[-2]
            and macd_line.iloc[-1] < signal_line.iloc[-1]
        )

        orders: list[Order] = []

        if current_rsi < self.params["oversold_threshold"] and macd_crossed_above:
            logger.info(
                "BUY signal: RSI=%.2f (oversold), MACD crossed above signal.", current_rsi
            )
            orders.append(
                Order(
                    symbol=self.symbol,
                    side=OrderSide.BUY,
                    quantity=self.params["order_quantity"],
                    order_type=OrderType.MARKET,
                )
            )

        elif current_rsi > self.params["overbought_threshold"] and macd_crossed_below:
            logger.info(
                "SELL signal: RSI=%.2f (overbought), MACD crossed below signal.", current_rsi
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
