from __future__ import annotations

import logging
import pandas as pd

from broker.order_models import Order, OrderSide, OrderType
from .base import BaseStrategy
from .indicators import ema, rsi, macd, atr

logger = logging.getLogger(__name__)


class SwingStrategy(BaseStrategy):
    """Multi-signal confluence swing trading strategy.

    This strategy holds positions for days to weeks, entering only when
    multiple independent signals align. The goal is high-probability
    entries with dynamic ATR-based risk management.

    ── ENTRY (LONG) — ALL conditions must be true ──────────────────────
    1. Trend filter    : Close > slow EMA (trading with the macro trend)
    2. Momentum shift  : Fast EMA crosses above mid EMA (short-term trend turn)
    3. RSI sweet spot  : RSI between 40–60 (not overbought — catching early)
    4. Volume surge    : Current bar volume > volume_factor × avg volume
    5. MACD momentum   : MACD histogram > 0 and increasing from prior bar

    ── ENTRY (SHORT) — mirror of the above ─────────────────────────────
    1. Close < slow EMA
    2. Fast EMA crosses below mid EMA
    3. RSI between 40–60
    4. Volume surge
    5. MACD histogram < 0 and decreasing

    ── EXIT / RISK MANAGEMENT ──────────────────────────────────────────
    • Stop-loss        : Entry ∓ atr_stop_mult × ATR (volatility-adaptive)
    • Take-profit      : Entry ± atr_tp_mult × ATR
    • Trailing stop    : After price moves atr_trail_trigger × ATR in our
                         favor, trail a stop at atr_trail_dist × ATR from
                         the best price since entry.
    • Time stop        : Exit if held longer than max_hold_bars bars
                         (prevents capital lock-up in dead trades).
    • Trend invalidation: Exit long if close drops below slow EMA;
                          exit short if close rises above slow EMA.

    Default parameters:
        ema_fast            = 9
        ema_mid             = 21
        ema_slow            = 50
        rsi_period          = 14
        rsi_entry_low       = 40
        rsi_entry_high      = 60
        macd_fast           = 12
        macd_slow           = 26
        macd_signal         = 9
        atr_period          = 14
        atr_stop_mult       = 2.0      stop at 2 × ATR
        atr_tp_mult         = 3.0      take profit at 3 × ATR (1.5:1 R:R)
        atr_trail_trigger   = 1.5      activate trailing stop after 1.5 × ATR profit
        atr_trail_dist      = 1.5      trail at 1.5 × ATR from best price
        volume_period       = 20       lookback for average volume
        volume_factor       = 1.2      volume must exceed 120% of average
        max_hold_bars       = 60       ~12 trading days on 5-min bars (adjustable)
        order_quantity      = 1
    """

    DEFAULT_PARAMS = {
        # EMAs
        "ema_fast": 9,
        "ema_mid": 21,
        "ema_slow": 50,
        # RSI
        "rsi_period": 14,
        "rsi_entry_low": 40,
        "rsi_entry_high": 60,
        # MACD
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        # ATR & risk
        "atr_period": 14,
        "atr_stop_mult": 2.0,
        "atr_tp_mult": 3.0,
        "atr_trail_trigger": 1.5,
        "atr_trail_dist": 1.5,
        # Volume
        "volume_period": 20,
        "volume_factor": 1.2,
        # Position management
        "max_hold_bars": 60,
        "order_quantity": 1,
    }

    def __init__(self, symbol: str, params: dict | None = None) -> None:
        merged = {**self.DEFAULT_PARAMS, **(params or {})}
        super().__init__(symbol, merged)

        # Internal position state
        self._position: int = 0          # +1 long, -1 short, 0 flat
        self._entry_price: float = 0.0
        self._entry_atr: float = 0.0
        self._bars_held: int = 0
        self._best_price: float = 0.0    # best price since entry (for trailing)

    # ── public interface ──────────────────────────────────────────────

    def on_bar(self, bars: pd.DataFrame) -> list[Order]:
        p = self.params
        min_bars = max(p["ema_slow"], p["macd_slow"] + p["macd_signal"], p["volume_period"]) + 2
        if len(bars) < min_bars:
            return []

        close = bars["close"]
        high = bars["high"]
        low = bars["low"]
        volume = bars["volume"]
        current_close = close.iloc[-1]

        # ── compute all indicators once ──
        ema_fast_s = ema(close, p["ema_fast"])
        ema_mid_s = ema(close, p["ema_mid"])
        ema_slow_s = ema(close, p["ema_slow"])
        rsi_s = rsi(close, p["rsi_period"])
        macd_line, signal_line, histogram = macd(
            close, fast=p["macd_fast"], slow=p["macd_slow"], signal=p["macd_signal"],
        )
        atr_s = atr(high, low, close, p["atr_period"])
        avg_volume = volume.rolling(window=p["volume_period"]).mean()

        current_atr = atr_s.iloc[-1]
        current_rsi = rsi_s.iloc[-1]
        current_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2]
        current_vol = volume.iloc[-1]
        current_avg_vol = avg_volume.iloc[-1]

        orders: list[Order] = []

        # ── if in a position, check exits first ──
        if self._position != 0:
            self._bars_held += 1
            self._update_best_price(current_close)

            exit_reason = self._check_exit(
                current_close, current_atr, ema_slow_s.iloc[-1],
            )
            if exit_reason:
                side = OrderSide.SELL if self._position > 0 else OrderSide.BUY
                logger.info(
                    "EXIT %s — reason: %s | entry=%.4f close=%.4f bars_held=%d",
                    "LONG" if self._position > 0 else "SHORT",
                    exit_reason,
                    self._entry_price,
                    current_close,
                    self._bars_held,
                )
                orders.append(Order(
                    symbol=self.symbol,
                    side=side,
                    quantity=p["order_quantity"],
                    order_type=OrderType.MARKET,
                ))
                self._reset_position()
                return orders

            # still in position — no new entries
            return []

        # ── flat: check entry signals ──
        ema_fast_cross_above_mid = (
            ema_fast_s.iloc[-2] <= ema_mid_s.iloc[-2]
            and ema_fast_s.iloc[-1] > ema_mid_s.iloc[-1]
        )
        ema_fast_cross_below_mid = (
            ema_fast_s.iloc[-2] >= ema_mid_s.iloc[-2]
            and ema_fast_s.iloc[-1] < ema_mid_s.iloc[-1]
        )

        rsi_in_zone = p["rsi_entry_low"] <= current_rsi <= p["rsi_entry_high"]
        volume_surge = current_vol > p["volume_factor"] * current_avg_vol

        # ── LONG entry ──
        if (
            current_close > ema_slow_s.iloc[-1]          # above macro trend
            and ema_fast_cross_above_mid                   # momentum shift
            and rsi_in_zone                                # not overbought
            and volume_surge                               # institutional interest
            and current_hist > 0                           # MACD positive
            and current_hist > prev_hist                   # and accelerating
        ):
            logger.info(
                "LONG ENTRY — close=%.4f ema_slow=%.4f rsi=%.2f vol=%d avg_vol=%d hist=%.4f atr=%.4f",
                current_close,
                ema_slow_s.iloc[-1],
                current_rsi,
                current_vol,
                current_avg_vol,
                current_hist,
                current_atr,
            )
            orders.append(Order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=p["order_quantity"],
                order_type=OrderType.MARKET,
            ))
            self._open_position(+1, current_close, current_atr)

        # ── SHORT entry ──
        elif (
            current_close < ema_slow_s.iloc[-1]           # below macro trend
            and ema_fast_cross_below_mid                    # momentum shift down
            and rsi_in_zone                                 # not oversold
            and volume_surge                                # institutional interest
            and current_hist < 0                            # MACD negative
            and current_hist < prev_hist                    # and accelerating down
        ):
            logger.info(
                "SHORT ENTRY — close=%.4f ema_slow=%.4f rsi=%.2f vol=%d avg_vol=%d hist=%.4f atr=%.4f",
                current_close,
                ema_slow_s.iloc[-1],
                current_rsi,
                current_vol,
                current_avg_vol,
                current_hist,
                current_atr,
            )
            orders.append(Order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                quantity=p["order_quantity"],
                order_type=OrderType.MARKET,
            ))
            self._open_position(-1, current_close, current_atr)

        return orders

    def on_start(self) -> None:
        self._reset_position()
        logger.info("SwingStrategy started for %s", self.symbol)

    def on_stop(self) -> None:
        if self._position != 0:
            logger.warning(
                "SwingStrategy stopped while in %s position (entry=%.4f, bars_held=%d).",
                "LONG" if self._position > 0 else "SHORT",
                self._entry_price,
                self._bars_held,
            )

    # ── internal helpers ──────────────────────────────────────────────

    def _open_position(self, direction: int, price: float, current_atr: float) -> None:
        self._position = direction
        self._entry_price = price
        self._entry_atr = current_atr
        self._bars_held = 0
        self._best_price = price

    def _reset_position(self) -> None:
        self._position = 0
        self._entry_price = 0.0
        self._entry_atr = 0.0
        self._bars_held = 0
        self._best_price = 0.0

    def _update_best_price(self, current_close: float) -> None:
        if self._position > 0:
            self._best_price = max(self._best_price, current_close)
        elif self._position < 0:
            self._best_price = min(self._best_price, current_close)

    def _check_exit(
        self,
        current_close: float,
        current_atr: float,
        ema_slow_val: float,
    ) -> str | None:
        """Return an exit reason string, or None to hold."""
        p = self.params
        entry = self._entry_price
        entry_atr = self._entry_atr

        if self._position > 0:
            # ── LONG exits ──
            stop_loss = entry - p["atr_stop_mult"] * entry_atr
            take_profit = entry + p["atr_tp_mult"] * entry_atr

            if current_close <= stop_loss:
                return f"stop-loss hit ({current_close:.4f} <= {stop_loss:.4f})"

            if current_close >= take_profit:
                return f"take-profit hit ({current_close:.4f} >= {take_profit:.4f})"

            # Trailing stop: activate once we're atr_trail_trigger × ATR in profit
            profit_distance = self._best_price - entry
            if profit_distance >= p["atr_trail_trigger"] * entry_atr:
                trail_stop = self._best_price - p["atr_trail_dist"] * entry_atr
                if current_close <= trail_stop:
                    return (
                        f"trailing stop hit (close={current_close:.4f} "
                        f"<= best={self._best_price:.4f} - trail={trail_stop:.4f})"
                    )

            # Trend invalidation
            if current_close < ema_slow_val:
                return f"trend invalidation (close={current_close:.4f} < ema_slow={ema_slow_val:.4f})"

        else:
            # ── SHORT exits ──
            stop_loss = entry + p["atr_stop_mult"] * entry_atr
            take_profit = entry - p["atr_tp_mult"] * entry_atr

            if current_close >= stop_loss:
                return f"stop-loss hit ({current_close:.4f} >= {stop_loss:.4f})"

            if current_close <= take_profit:
                return f"take-profit hit ({current_close:.4f} <= {take_profit:.4f})"

            # Trailing stop (short: best price is lowest, trail above)
            profit_distance = entry - self._best_price
            if profit_distance >= p["atr_trail_trigger"] * entry_atr:
                trail_stop = self._best_price + p["atr_trail_dist"] * entry_atr
                if current_close >= trail_stop:
                    return (
                        f"trailing stop hit (close={current_close:.4f} "
                        f">= best={self._best_price:.4f} + trail={trail_stop:.4f})"
                    )

            # Trend invalidation
            if current_close > ema_slow_val:
                return f"trend invalidation (close={current_close:.4f} > ema_slow={ema_slow_val:.4f})"

        # Time stop (applies to both directions)
        if self._bars_held >= p["max_hold_bars"]:
            return f"time stop ({self._bars_held} bars >= max {p['max_hold_bars']})"

        return None
