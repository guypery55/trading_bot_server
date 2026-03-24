import asyncio
import logging
import threading
from datetime import datetime, timezone

from ibapi.client import EClient
from ibapi.commission_report import CommissionReport
from ibapi.common import OrderId, TickerId
from ibapi.contract import Contract
from ibapi.execution import Execution
from ibapi.order import Order as IBOrder
from ibapi.wrapper import EWrapper

from config.settings import Settings
from .base import BrokerInterface
from .order_models import AccountSummary, Fill, Order, OrderSide, OrderType, Position

logger = logging.getLogger(__name__)

# Error codes that are purely informational (market data farm messages etc.)
_IGNORED_ERROR_CODES = {2104, 2106, 2107, 2108, 2119, 2158}


class _IBKRApp(EWrapper, EClient):
    """Low-level ibapi app that merges EWrapper callbacks with EClient requests.

    Runs in its own background thread via EClient.run(). All state is
    accessed from the asyncio thread through threading.Event / queue.Queue.
    """

    def __init__(self) -> None:
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)

        # Connection
        self._connected = threading.Event()
        self._next_order_id: int = 1

        # Historical data:  reqId -> list[bar_dict]
        self._hist_bars: dict[int, list] = {}
        self._hist_events: dict[int, threading.Event] = {}

        # Order fills: orderId -> dict with execution info
        self._fills: dict[int, dict] = {}
        self._fill_events: dict[int, threading.Event] = {}

        # Positions
        self._positions: list[dict] = []
        self._positions_event = threading.Event()

        # Account summary
        self._account_values: dict[str, str] = {}
        self._account_event = threading.Event()

        # Real-time bars: called from ibapi thread, scheduled on the asyncio loop
        self.on_realtime_bar: callable | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def nextValidId(self, orderId: OrderId) -> None:
        self._next_order_id = orderId
        self._connected.set()
        logger.info("IBKR connected. Next valid order ID: %s", orderId)

    def connectAck(self) -> None:
        logger.debug("connectAck received.")

    def error(
        self,
        reqId: TickerId,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        if errorCode in _IGNORED_ERROR_CODES:
            logger.debug("IBKR info [%s]: %s", errorCode, errorString)
            return
        if errorCode == 502:
            logger.critical("Cannot connect to IBKR: %s", errorString)
        elif errorCode == 162:
            # Historical data request error — unblock waiting event
            if reqId in self._hist_events:
                logger.warning("Historical data error for req %s: %s", reqId, errorString)
                self._hist_events[reqId].set()
        else:
            logger.error("IBKR error [req=%s code=%s]: %s", reqId, errorCode, errorString)

    # ── Historical data ────────────────────────────────────────────────────────

    def historicalData(self, reqId: int, bar) -> None:
        self._hist_bars.setdefault(reqId, []).append({
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })

    def historicalDataEnd(self, reqId: int, start: str, end: str) -> None:
        if reqId in self._hist_events:
            self._hist_events[reqId].set()

    # ── Real-time bars ─────────────────────────────────────────────────────────

    def realtimeBar(
        self,
        reqId: int,
        time: int,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: int,
        wap: float,
        count: int,
    ) -> None:
        if self.on_realtime_bar and self._loop:
            bar = {
                "date": datetime.fromtimestamp(time, tz=timezone.utc),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
            # Schedule callback safely onto the asyncio event loop
            self._loop.call_soon_threadsafe(self.on_realtime_bar, bar)

    # ── Orders ─────────────────────────────────────────────────────────────────

    def execDetails(self, reqId: int, contract: Contract, execution: Execution) -> None:
        oid = execution.orderId
        self._fills.setdefault(oid, {"executions": [], "commissions": [], "filled": False})
        self._fills[oid]["executions"].append(execution)

    def commissionReport(self, commissionReport: CommissionReport) -> None:
        for data in self._fills.values():
            for ex in data["executions"]:
                if ex.execId == commissionReport.execId:
                    data["commissions"].append(commissionReport.commission)

    def orderStatus(
        self,
        orderId: OrderId,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        logger.debug(
            "Order %s → %s (filled=%.2f @ %.4f)",
            orderId, status, filled, avgFillPrice,
        )
        if status == "Filled" and orderId in self._fill_events:
            data = self._fills.setdefault(
                orderId, {"executions": [], "commissions": [], "filled": False}
            )
            data["avg_fill_price"] = avgFillPrice
            data["filled_qty"] = filled
            data["filled"] = True
            self._fill_events[orderId].set()

    # ── Positions ──────────────────────────────────────────────────────────────

    def position(self, account: str, contract: Contract, position: float, avgCost: float) -> None:
        self._positions.append({
            "symbol": contract.symbol,
            "quantity": position,
            "average_cost": avgCost,
        })

    def positionEnd(self) -> None:
        self._positions_event.set()

    # ── Account summary ────────────────────────────────────────────────────────

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str) -> None:
        self._account_values[tag] = value

    def accountSummaryEnd(self, reqId: int) -> None:
        self._account_event.set()


class IBKRBroker(BrokerInterface):
    """Interactive Brokers broker implementation using the official ibapi library.

    Runs EClient.run() in a daemon thread. All async methods bridge to ibapi
    callbacks via threading.Event without blocking the asyncio event loop.
    """

    def __init__(self, settings: Settings) -> None:
        self._app = _IBKRApp()
        self._settings = settings
        self._thread: threading.Thread | None = None
        self._req_counter: int = 2000  # starting reqId for data requests

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        logger.info(
            "Connecting to IBKR %s on %s:%s (clientId=%s)",
            self._settings.trading_mode.value.upper(),
            self._settings.ibkr_host,
            self._settings.ibkr_port,
            self._settings.ibkr_client_id,
        )

        self._app._loop = asyncio.get_running_loop()
        self._app.connect(
            self._settings.ibkr_host,
            self._settings.ibkr_port,
            self._settings.ibkr_client_id,
        )
        self._thread = threading.Thread(target=self._app.run, daemon=True, name="ibapi-thread")
        self._thread.start()

        connected = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._app._connected.wait(timeout=15)
        )
        if not connected:
            raise ConnectionError(
                f"Timed out connecting to IBKR on port {self._settings.ibkr_port}. "
                "Make sure IB Gateway is running with API connections enabled."
            )

        # Request delayed market data (type 3) as fallback when the account
        # doesn't have a real-time data subscription.  Type 4 = delayed-frozen.
        # This avoids error 420 "No market data permissions for ISLAND STK".
        self._app.reqMarketDataType(3)
        logger.info("IBKR broker ready (market data: delayed).")

    async def disconnect(self) -> None:
        if self._app.isConnected():
            self._app.disconnect()
            logger.info("Disconnected from IBKR.")

    @property
    def is_connected(self) -> bool:
        return self._app.isConnected()

    # ── Orders ─────────────────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> Fill:
        order_id = self._app._next_order_id
        self._app._next_order_id += 1

        contract = self._make_contract(order.symbol)
        ib_order = self._make_ib_order(order, order_id)

        event = threading.Event()
        self._app._fill_events[order_id] = event
        self._app._fills[order_id] = {"executions": [], "commissions": [], "filled": False}

        logger.info(
            "Placing %s %s order: %.2f x %s",
            order.order_type.value, order.side.value, order.quantity, order.symbol,
        )
        self._app.placeOrder(order_id, contract, ib_order)

        filled = await asyncio.get_running_loop().run_in_executor(
            None, lambda: event.wait(timeout=30)
        )
        if not filled:
            raise TimeoutError(
                f"Order {order_id} ({order.symbol}) timed out waiting for fill after 30s."
            )

        data = self._app._fills[order_id]
        avg_price = data.get("avg_fill_price", order.limit_price or 0.0)
        filled_qty = data.get("filled_qty", order.quantity)
        commission = sum(data.get("commissions", []))

        fill = Fill(
            order_id=str(order_id),
            symbol=order.symbol,
            side=order.side,
            filled_quantity=filled_qty,
            average_price=avg_price,
            commission=commission,
            timestamp=datetime.now(timezone.utc),
        )
        logger.info("Fill: %s %s @ %.4f (commission: %.4f)", fill.side.value, fill.symbol, fill.average_price, fill.commission)
        return fill

    async def cancel_order(self, order_id: str) -> None:
        self._app.cancelOrder(int(order_id), "")
        logger.info("Cancel request sent for order %s.", order_id)

    # ── Account / Positions ────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        self._app._positions = []
        self._app._positions_event.clear()
        self._app.reqPositions()

        done = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._app._positions_event.wait(timeout=10)
        )
        self._app.cancelPositions()
        if not done:
            logger.warning("Timed out waiting for positions response.")
            return []

        return [
            Position(symbol=p["symbol"], quantity=p["quantity"], average_cost=p["average_cost"])
            for p in self._app._positions
            if p["quantity"] != 0
        ]

    async def get_account_summary(self) -> AccountSummary:
        req_id = self.next_req_id()
        self._app._account_values = {}
        self._app._account_event.clear()
        self._app.reqAccountSummary(req_id, "All", "NetLiquidation,BuyingPower,TotalCashValue")

        done = await asyncio.get_running_loop().run_in_executor(
            None, lambda: self._app._account_event.wait(timeout=10)
        )
        self._app.cancelAccountSummary(req_id)
        if not done:
            logger.warning("Timed out waiting for account summary.")

        vals = self._app._account_values
        return AccountSummary(
            net_liquidation=float(vals.get("NetLiquidation", 0)),
            buying_power=float(vals.get("BuyingPower", 0)),
            cash_balance=float(vals.get("TotalCashValue", 0)),
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def next_req_id(self) -> int:
        self._req_counter += 1
        return self._req_counter

    @property
    def app(self) -> _IBKRApp:
        """Expose the underlying _IBKRApp for use by MarketDataFeed."""
        return self._app

    @staticmethod
    def _make_contract(symbol: str) -> Contract:
        c = Contract()
        c.symbol = symbol
        c.secType = "STK"
        c.exchange = "SMART"
        c.currency = "USD"
        return c

    @staticmethod
    def _make_ib_order(order: Order, order_id: int) -> IBOrder:
        ib = IBOrder()
        ib.orderId = order_id
        ib.action = order.side.value          # "BUY" or "SELL"
        ib.totalQuantity = order.quantity

        if order.order_type == OrderType.MARKET:
            ib.orderType = "MKT"
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit_price is required for LIMIT orders.")
            ib.orderType = "LMT"
            ib.lmtPrice = order.limit_price
        elif order.order_type == OrderType.STOP:
            if order.stop_price is None:
                raise ValueError("stop_price is required for STOP orders.")
            ib.orderType = "STP"
            ib.auxPrice = order.stop_price
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        return ib
