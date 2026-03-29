import asyncio
import logging
from collections.abc import Awaitable, Callable

import pandas as pd

logger = logging.getLogger(__name__)

# Type alias for bar callbacks registered by the engine.
BarCallback = Callable[[pd.DataFrame], Awaitable[None]]

# Seconds to wait before each successive retry on a 429 / 503 pacing response.
# The Gateway's penalty box lasts 10 minutes, so if we somehow still hit a
# limit we back off hard rather than hammering and extending the ban.
_RETRY_DELAYS: tuple[int, ...] = (10, 30, 60)

# Map ibapi-style bar-size strings to Web API format.
_BAR_SIZE_MAP: dict[str, str] = {
    "1 min":   "1min",  "1 mins":  "1min",
    "2 mins":  "2min",
    "3 mins":  "3min",
    "5 mins":  "5min",
    "10 mins": "10min",
    "15 mins": "15min",
    "30 mins": "30min",
    "1 hour":  "1h",    "1 hours": "1h",
    "2 hours": "2h",
    "3 hours": "3h",
    "4 hours": "4h",
    "8 hours": "8h",
    "1 day":   "1d",    "1 days":  "1d",
    "1 week":  "1w",
}

# Polling interval in seconds per bar size.
_BAR_SECONDS: dict[str, int] = {
    "1min": 60,   "2min": 120,  "3min": 180,  "5min": 300,
    "10min": 600, "15min": 900, "30min": 1800,
    "1h": 3600,   "2h": 7200,   "3h": 10800,  "4h": 14400, "8h": 28800,
    "1d": 86400,  "1w": 604800,
}


class MarketDataFeed:
    """Fetches historical and real-time bar data from IBKR via the Web API.

    Historical data is fetched once on startup.  Real-time bars are simulated
    by polling /iserver/marketdata/history at each bar interval and emitting
    any bars that are newer than the last seen timestamp.

    Usage:
        feed = MarketDataFeed(broker, symbol="AAPL", bar_size="5 mins")
        await feed.load_history(lookback_days=30)
        feed.subscribe(engine._on_new_bar)
        await feed.start_streaming()
    """

    def __init__(self, broker, symbol: str, bar_size: str = "5 mins") -> None:
        from broker.ibkr_broker import IBKRBroker
        self._broker: IBKRBroker = broker
        self._symbol = symbol
        self._bar_size = _BAR_SIZE_MAP.get(bar_size.lower(), bar_size)
        self._poll_interval = _BAR_SECONDS.get(self._bar_size, 300)
        self._bars: list[dict] = []
        self._callbacks: list[BarCallback] = []
        self._stream_task: asyncio.Task | None = None
        self._last_bar_time: int = 0   # epoch-ms of the last bar we have seen

    # ── Historical data ────────────────────────────────────────────────────────

    async def load_history(self, lookback_days: int = 30) -> pd.DataFrame:
        """Fetch historical OHLCV bars from the IBKR Web API.

        Retries up to 3 times on 429 / 503 (pacing violations) using the
        back-off schedule in _RETRY_DELAYS before giving up and returning
        whatever bars were collected so far.
        """
        conid = await self._broker.resolve_conid(self._symbol)
        period = f"{lookback_days}d"

        logger.info(
            "Fetching %s of history for %s (%s)...",
            period, self._symbol, self._bar_size,
        )

        delays = (0, *_RETRY_DELAYS)   # first attempt has no pre-delay
        for attempt, wait in enumerate(delays):
            if wait:
                logger.warning(
                    "History pacing limit hit for %s — waiting %ds before retry %d/%d.",
                    self._symbol, wait, attempt, len(_RETRY_DELAYS),
                )
                await asyncio.sleep(wait)

            try:
                r = await self._broker._client.get(
                    f"{self._broker._base_url}/iserver/marketdata/history",
                    params={
                        "conid": conid,
                        "period": period,
                        "bar": self._bar_size,
                        "outsideRth": False,
                    },
                )
            except Exception as exc:
                logger.warning("History request failed for %s: %s", self._symbol, exc)
                continue

            if r.status_code in (429, 503):
                if attempt < len(_RETRY_DELAYS):
                    continue        # retry with next back-off delay
                logger.error(
                    "Giving up on history for %s after %d attempts (last status %d).",
                    self._symbol, attempt + 1, r.status_code,
                )
                return self.to_dataframe()

            try:
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                logger.warning("Failed to parse history for %s: %s", self._symbol, exc)
                return self.to_dataframe()

            self._bars = [self._parse_bar(b) for b in data.get("data", [])]
            if self._bars:
                self._last_bar_time = self._bars[-1]["_t"]

            logger.info("Loaded %d historical bars for %s.", len(self._bars), self._symbol)
            return self.to_dataframe()

        return self.to_dataframe()

    # ── Real-time streaming (polling) ──────────────────────────────────────────

    def subscribe(self, callback: BarCallback) -> None:
        """Register an async callback to be called on each new bar."""
        self._callbacks.append(callback)

    async def start_streaming(self) -> None:
        """Poll the Web API for new bars once per bar interval."""
        logger.info(
            "Starting bar polling for %s (%s, interval=%ds).",
            self._symbol, self._bar_size, self._poll_interval,
        )
        self._stream_task = asyncio.create_task(self._poll_loop())

    async def stop_streaming(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped bar polling for %s.", self._symbol)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        """Return the bar buffer as a sorted DataFrame (OHLCV columns only)."""
        if not self._bars:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(self._bars).drop(columns=["_t"])
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    # ── Private ────────────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            await self._fetch_and_emit()

    async def _fetch_and_emit(self) -> None:
        conid = await self._broker.resolve_conid(self._symbol)
        try:
            r = await self._broker._client.get(
                f"{self._broker._base_url}/iserver/marketdata/history",
                params={
                    "conid": conid,
                    "period": "1d",
                    "bar": self._bar_size,
                    "outsideRth": False,
                },
            )
        except Exception as exc:
            logger.warning("Polling request failed for %s: %s", self._symbol, exc)
            return

        if r.status_code in (429, 503):
            logger.warning(
                "Polling pacing limit (%d) for %s — skipping this interval.",
                r.status_code, self._symbol,
            )
            return

        try:
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning("Polling failed for %s: %s", self._symbol, exc)
            return

        new_bars = [
            self._parse_bar(b)
            for b in data.get("data", [])
            if b.get("t", 0) > self._last_bar_time
        ]
        if not new_bars:
            return

        self._bars.extend(new_bars)
        self._last_bar_time = new_bars[-1]["_t"]

        df = self.to_dataframe()
        for cb in self._callbacks:
            asyncio.create_task(cb(df))

    @staticmethod
    def _parse_bar(b: dict) -> dict:
        """Normalise a Web API bar dict to our internal OHLCV format.

        The Web API returns bars as:
            {"t": <epoch_ms>, "o": open, "h": high, "l": low, "c": close, "v": volume}
        """
        t: int = int(b.get("t", 0))
        return {
            "_t":    t,                                           # raw epoch-ms for dedup
            "date":  pd.Timestamp(t, unit="ms").isoformat(),
            "open":  float(b.get("o", b.get("open",  0))),
            "high":  float(b.get("h", b.get("high",  0))),
            "low":   float(b.get("l", b.get("low",   0))),
            "close": float(b.get("c", b.get("close", 0))),
            "volume":float(b.get("v", b.get("volume", 0))),
        }
