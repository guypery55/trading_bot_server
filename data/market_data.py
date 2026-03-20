import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import pandas as pd
from ib_insync import IB, BarData, RealTimeBar, Stock

logger = logging.getLogger(__name__)

# Type alias for the bar callback the engine registers
BarCallback = Callable[[pd.DataFrame], Awaitable[None]]


class MarketDataFeed:
    """Fetches historical and real-time bar data from IBKR via ib_insync.

    Usage:
        feed = MarketDataFeed(ib, symbol="AAPL", bar_size="5 mins")
        await feed.load_history(lookback_days=30)
        feed.subscribe(engine._on_new_bar)
        # Now on each new bar, engine._on_new_bar(bars_df) is awaited.
    """

    def __init__(self, ib: IB, symbol: str, bar_size: str = "5 mins") -> None:
        self._ib = ib
        self._symbol = symbol
        self._bar_size = bar_size
        self._contract = Stock(symbol, "SMART", "USD")
        self._bars: list[dict] = []
        self._callbacks: list[BarCallback] = []
        self._realtime_bars = None

    # ── Historical data ───────────────────────────────────────────────────────

    async def load_history(self, lookback_days: int = 30) -> pd.DataFrame:
        """Fetch historical bars and store them as the initial bar buffer."""
        end_dt = datetime.now()
        duration = f"{lookback_days} D"

        logger.info(
            "Fetching %s days of historical bars for %s (%s)...",
            lookback_days,
            self._symbol,
            self._bar_size,
        )

        raw = await self._ib.reqHistoricalDataAsync(
            contract=self._contract,
            endDateTime=end_dt,
            durationStr=duration,
            barSizeSetting=self._bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )

        self._bars = [self._bar_to_dict(b) for b in raw]
        logger.info("Loaded %s historical bars.", len(self._bars))
        return self.to_dataframe()

    # ── Real-time subscription ────────────────────────────────────────────────

    def subscribe(self, callback: BarCallback) -> None:
        """Register a callback to be called on each new completed bar."""
        self._callbacks.append(callback)

    async def start_streaming(self) -> None:
        """Subscribe to real-time 5-second bars and bridge into the bar_size aggregator."""
        logger.info("Starting real-time bar stream for %s.", self._symbol)
        self._realtime_bars = self._ib.reqRealTimeBars(
            contract=self._contract,
            barSize=5,           # IBKR only supports 5-second real-time bars
            whatToShow="TRADES",
            useRTH=True,
        )
        self._realtime_bars.updateEvent += self._on_realtime_bar

    async def stop_streaming(self) -> None:
        if self._realtime_bars is not None:
            self._ib.cancelRealTimeBars(self._realtime_bars)
            logger.info("Stopped real-time bar stream for %s.", self._symbol)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_realtime_bar(self, bars, has_new_bar: bool) -> None:
        """Called by ib_insync on each new 5-second bar update."""
        if not has_new_bar or not bars:
            return
        latest: RealTimeBar = bars[-1]
        self._bars.append({
            "date": latest.time,
            "open": latest.open_,
            "high": latest.high,
            "low": latest.low,
            "close": latest.close,
            "volume": latest.volume,
        })
        df = self.to_dataframe()
        for cb in self._callbacks:
            asyncio.ensure_future(cb(df))

    def to_dataframe(self) -> pd.DataFrame:
        """Return the current bar buffer as a DataFrame."""
        if not self._bars:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(self._bars)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    @staticmethod
    def _bar_to_dict(bar: BarData) -> dict:
        return {
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        }
