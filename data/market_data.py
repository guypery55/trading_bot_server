import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable

import pandas as pd
from ibapi.contract import Contract

logger = logging.getLogger(__name__)

# Type alias for the bar callback registered by the engine
BarCallback = Callable[[pd.DataFrame], Awaitable[None]]


class MarketDataFeed:
    """Fetches historical and real-time bar data from IBKR via ibapi.

    Usage:
        feed = MarketDataFeed(broker, symbol="AAPL", bar_size="5 mins")
        await feed.load_history(lookback_days=30)
        feed.subscribe(engine._on_new_bar)
        await feed.start_streaming()
    """

    def __init__(self, broker, symbol: str, bar_size: str = "5 mins") -> None:
        # Importing here to avoid circular import at module level
        from broker.ibkr_broker import IBKRBroker
        self._broker: IBKRBroker = broker
        self._symbol = symbol
        self._bar_size = bar_size
        self._bars: list[dict] = []
        self._callbacks: list[BarCallback] = []
        self._realtime_req_id: int | None = None

    # ── Historical data ────────────────────────────────────────────────────────

    async def load_history(self, lookback_days: int = 30) -> pd.DataFrame:
        """Fetch historical OHLCV bars and populate the internal bar buffer."""
        req_id = self._broker.next_req_id()
        app = self._broker.app

        app._hist_bars[req_id] = []
        event = threading.Event()
        app._hist_events[req_id] = event

        contract = self._make_contract()
        duration = f"{lookback_days} D"

        logger.info(
            "Fetching %s days of history for %s (%s)...",
            lookback_days, self._symbol, self._bar_size,
        )

        app.reqHistoricalData(
            req_id,
            contract,
            "",                 # endDateTime — empty string means "now"
            duration,
            self._bar_size,
            "ADJUSTED_LAST",   # works with delayed data; TRADES requires a subscription
            1,                  # useRTH
            1,                  # formatDate (1 = yyyyMMdd HH:mm:ss)
            False,              # keepUpToDate
            [],                 # chartOptions
        )

        done = await asyncio.get_running_loop().run_in_executor(
            None, lambda: event.wait(timeout=60)
        )
        if not done:
            logger.warning("Timed out waiting for historical data for %s.", self._symbol)
            return self.to_dataframe()

        self._bars = app._hist_bars.get(req_id, [])
        logger.info("Loaded %s historical bars for %s.", len(self._bars), self._symbol)
        return self.to_dataframe()

    # ── Real-time streaming ────────────────────────────────────────────────────

    def subscribe(self, callback: BarCallback) -> None:
        """Register a coroutine callback to be called on each new real-time bar."""
        self._callbacks.append(callback)

    async def start_streaming(self) -> None:
        """Stream live bars using reqHistoricalData with keepUpToDate=True.

        Unlike reqRealTimeBars (which needs real-time permissions and only
        supports 5-second bars), keepUpToDate respects reqMarketDataType(3)
        so it works with delayed data on paper accounts.
        """
        req_id = self._broker.next_req_id()
        self._realtime_req_id = req_id

        loop = asyncio.get_running_loop()

        def _on_bar(bar_dict: dict) -> None:
            """Called from ibapi thread via call_soon_threadsafe."""
            self._bars.append(bar_dict)
            df = self.to_dataframe()
            for cb in self._callbacks:
                loop.create_task(cb(df))

        self._broker.app.on_realtime_bar = _on_bar

        logger.info("Starting streaming bars for %s (%s, req_id=%s).", self._symbol, self._bar_size, req_id)
        self._broker.app.reqHistoricalData(
            req_id,
            self._make_contract(),
            "",                 # endDateTime — empty = now
            "60 S",             # durationStr — small window, keepUpToDate streams from here
            self._bar_size,
            "ADJUSTED_LAST",   # consistent with history fetch; works with delayed data
            1,                  # useRTH
            1,                  # formatDate
            True,               # keepUpToDate — streams live bar updates
            [],                 # chartOptions
        )

    async def stop_streaming(self) -> None:
        """Cancel the streaming historical data subscription."""
        if self._realtime_req_id is not None:
            self._broker.app.cancelHistoricalData(self._realtime_req_id)
            self._broker.app.on_realtime_bar = None
            logger.info("Stopped bar stream for %s.", self._symbol)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        """Return the current bar buffer as a sorted DataFrame."""
        if not self._bars:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(self._bars)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def _make_contract(self) -> Contract:
        c = Contract()
        c.symbol = self._symbol
        c.secType = "STK"
        c.exchange = "SMART"
        c.currency = "USD"
        return c
