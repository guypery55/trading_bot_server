import logging
from datetime import datetime

from ib_insync import IB, LimitOrder, MarketOrder, StopOrder, Stock, Trade

from config.settings import Settings
from .base import BrokerInterface
from .order_models import (
    AccountSummary,
    Fill,
    Order,
    OrderSide,
    OrderType,
    Position,
)

logger = logging.getLogger(__name__)


class IBKRBroker(BrokerInterface):
    """Interactive Brokers broker implementation using ib_insync.

    Connects to either TWS or IB Gateway depending on settings.
    Paper vs live trading is determined solely by the port number:
        paper + tws     -> 7497
        paper + gateway -> 4002
        live  + tws     -> 7496
        live  + gateway -> 4001
    """

    def __init__(self, settings: Settings) -> None:
        self._ib = IB()
        self._settings = settings

    # ── Connection ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        logger.info(
            "Connecting to IBKR %s on %s:%s (clientId=%s)",
            self._settings.trading_mode.value.upper(),
            self._settings.ibkr_host,
            self._settings.ibkr_port,
            self._settings.ibkr_client_id,
        )
        try:
            await self._ib.connectAsync(
                host=self._settings.ibkr_host,
                port=self._settings.ibkr_port,
                clientId=self._settings.ibkr_client_id,
            )
            logger.info("Connected to IBKR successfully.")
        except ConnectionRefusedError:
            raise ConnectionRefusedError(
                f"Could not connect to IBKR on port {self._settings.ibkr_port}. "
                "Make sure TWS or IB Gateway is running and API connections are enabled."
            )

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
            logger.info("Disconnected from IBKR.")

    @property
    def is_connected(self) -> bool:
        return self._ib.isConnected()

    # ── Orders ────────────────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> Fill:
        contract = Stock(order.symbol, "SMART", "USD")
        ib_order = self._build_ib_order(order)

        logger.info(
            "Placing %s %s order: %s x %s",
            order.order_type.value,
            order.side.value,
            order.quantity,
            order.symbol,
        )

        trade: Trade = self._ib.placeOrder(contract, ib_order)
        await self._ib.waitOnUpdate(timeout=30)

        fill = self._trade_to_fill(trade, order)
        logger.info("Order filled: %s @ %.4f", order.symbol, fill.average_price)
        return fill

    async def cancel_order(self, order_id: str) -> None:
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                logger.info("Cancelled order %s", order_id)
                return
        logger.warning("Order %s not found for cancellation.", order_id)

    # ── Account / Positions ───────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        raw = await self._ib.reqPositionsAsync()
        return [
            Position(
                symbol=pos.contract.symbol,
                quantity=pos.position,
                average_cost=pos.avgCost,
            )
            for pos in raw
            if pos.position != 0
        ]

    async def get_account_summary(self) -> AccountSummary:
        summary = await self._ib.reqAccountSummaryAsync()
        values: dict[str, float] = {}
        for item in summary:
            try:
                values[item.tag] = float(item.value)
            except (ValueError, TypeError):
                pass
        return AccountSummary(
            net_liquidation=values.get("NetLiquidation", 0.0),
            buying_power=values.get("BuyingPower", 0.0),
            cash_balance=values.get("TotalCashValue", 0.0),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_ib_order(self, order: Order):
        action = order.side.value  # "BUY" or "SELL"
        qty = order.quantity

        if order.order_type == OrderType.MARKET:
            return MarketOrder(action, qty)
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit_price is required for LIMIT orders.")
            return LimitOrder(action, qty, order.limit_price)
        elif order.order_type == OrderType.STOP:
            if order.stop_price is None:
                raise ValueError("stop_price is required for STOP orders.")
            return StopOrder(action, qty, order.stop_price)
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

    def _trade_to_fill(self, trade: Trade, original_order: Order) -> Fill:
        fills = trade.fills
        if fills:
            avg_price = sum(f.execution.price * f.execution.shares for f in fills) / sum(
                f.execution.shares for f in fills
            )
            filled_qty = sum(f.execution.shares for f in fills)
            commission = sum(f.commissionReport.commission for f in fills if f.commissionReport)
            ts = fills[-1].time if fills else datetime.utcnow()
        else:
            # Fallback for paper trading simulation where fills may not be immediate
            avg_price = original_order.limit_price or 0.0
            filled_qty = original_order.quantity
            commission = 0.0
            ts = datetime.utcnow()

        return Fill(
            order_id=str(trade.order.orderId),
            symbol=original_order.symbol,
            side=original_order.side,
            filled_quantity=filled_qty,
            average_price=avg_price,
            commission=commission,
            timestamp=ts,
        )

    # ── IB instance access (for MarketDataFeed) ───────────────────────────────

    @property
    def ib(self) -> IB:
        """Expose the underlying IB instance for use by MarketDataFeed."""
        return self._ib
