import asyncio
import logging
from datetime import datetime, timezone

import httpx

from config.settings import Settings
from .base import BrokerInterface
from .order_models import AccountSummary, Fill, Order, OrderType, Position

logger = logging.getLogger(__name__)


class IBKRBroker(BrokerInterface):
    """Interactive Brokers broker using the IBKR Web API (Client Portal Gateway).

    Requires the IB Client Portal Gateway to be running locally (default port 5000)
    with an active authenticated session.  Auth is handled by the Gateway; this
    client only needs to POST /tickle every 60 s to keep the session alive.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = f"https://{settings.ibkr_host}:{settings.ibkr_port}/v1/api"
        # CP Gateway uses a self-signed TLS cert — disable verification for local use.
        self._client = httpx.AsyncClient(verify=False, timeout=30.0)
        self._account_id: str | None = None
        self._conid_cache: dict[str, int] = {}
        self._tickle_task: asyncio.Task | None = None
        self._connected = False

    # ── Connection ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        logger.info(
            "Connecting to IBKR Web API at %s (mode=%s)",
            self._base_url,
            self._settings.trading_mode.value.upper(),
        )

        # Verify Gateway is running and the session is authenticated.
        # Retry a few times in case the brokerage session needs initialisation.
        for attempt in range(3):
            try:
                r = await self._client.get(f"{self._base_url}/iserver/auth/status")
                r.raise_for_status()
                status = r.json()
                if status.get("authenticated"):
                    break
                # Session connected but not authenticated — ask Gateway to init it.
                await self._client.post(
                    f"{self._base_url}/iserver/auth/ssodh/init",
                    json={"compete": True, "publish": True},
                )
                await asyncio.sleep(2)
            except Exception as exc:
                if attempt == 2:
                    raise ConnectionError(
                        f"Cannot reach IBKR Web API at {self._base_url}: {exc}. "
                        "Make sure IB Client Portal Gateway is running and you are "
                        "logged in via the browser."
                    ) from exc
                await asyncio.sleep(2)

        self._account_id = await self._get_account_id()
        self._connected = True
        self._tickle_task = asyncio.create_task(self._tickle_loop())
        logger.info("IBKR Web API connected. Account: %s", self._account_id)

    async def disconnect(self) -> None:
        self._connected = False
        if self._tickle_task:
            self._tickle_task.cancel()
            try:
                await self._tickle_task
            except asyncio.CancelledError:
                pass
        await self._client.aclose()
        logger.info("Disconnected from IBKR Web API.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Orders ─────────────────────────────────────────────────────────────────

    async def place_order(self, order: Order) -> Fill:
        conid = await self.resolve_conid(order.symbol)
        payload = self._build_order_payload(conid, order)

        logger.info(
            "Placing %s %s order: %.2f x %s",
            order.order_type.value, order.side.value, order.quantity, order.symbol,
        )

        r = await self._client.post(
            f"{self._base_url}/iserver/account/{self._account_id}/orders",
            json={"orders": [payload]},
        )
        r.raise_for_status()
        result = r.json()

        # The Web API sometimes requires confirmation of a reply message before
        # the order is submitted.  Loop until we get an order_id in the response.
        while isinstance(result, list) and result and "id" in result[0]:
            reply_id = result[0]["id"]
            logger.debug("Confirming order reply: %s", reply_id)
            r = await self._client.post(
                f"{self._base_url}/iserver/reply/{reply_id}",
                json={"confirmed": True},
            )
            r.raise_for_status()
            result = r.json()

        order_data = result[0] if isinstance(result, list) and result else result
        order_id = str(order_data.get("order_id", order_data.get("orderId", "unknown")))

        fill_price = await self._wait_for_fill(order_id, order)

        fill = Fill(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            filled_quantity=order.quantity,
            average_price=fill_price,
            commission=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        logger.info(
            "Fill: %s %s @ %.4f", fill.side.value, fill.symbol, fill.average_price
        )
        return fill

    async def cancel_order(self, order_id: str) -> None:
        r = await self._client.delete(
            f"{self._base_url}/iserver/account/{self._account_id}/order/{order_id}"
        )
        r.raise_for_status()
        logger.info("Cancelled order %s.", order_id)

    # ── Account / Positions ────────────────────────────────────────────────────

    async def get_positions(self) -> list[Position]:
        # /portfolio/accounts must be called first to initialise the portfolio session.
        await self._client.get(f"{self._base_url}/portfolio/accounts")

        r = await self._client.get(
            f"{self._base_url}/portfolio/{self._account_id}/positions/0"
        )
        r.raise_for_status()

        return [
            Position(
                symbol=p.get("contractDesc", p.get("ticker", str(p.get("conid", "")))),
                quantity=float(p["position"]),
                average_cost=float(p.get("avgCost", p.get("avgPrice", 0))),
                unrealized_pnl=float(p.get("unrealizedPnl", 0)),
            )
            for p in r.json()
            if float(p.get("position", 0)) != 0
        ]

    async def get_account_summary(self) -> AccountSummary:
        await self._client.get(f"{self._base_url}/portfolio/accounts")

        r = await self._client.get(
            f"{self._base_url}/portfolio/{self._account_id}/summary"
        )
        r.raise_for_status()
        data = r.json()

        def _amt(key: str) -> float:
            val = data.get(key, {})
            return float(val.get("amount", 0)) if isinstance(val, dict) else float(val or 0)

        return AccountSummary(
            net_liquidation=_amt("netliquidationvalue"),
            buying_power=_amt("buyingpower"),
            cash_balance=_amt("totalcashvalue"),
        )

    # ── Public helpers (used by MarketDataFeed) ────────────────────────────────

    async def resolve_conid(self, symbol: str) -> int:
        """Resolve a ticker symbol to an IBKR contract ID, with caching."""
        if symbol in self._conid_cache:
            return self._conid_cache[symbol]

        r = await self._client.post(
            f"{self._base_url}/iserver/secdef/search",
            json={"symbol": symbol, "name": False, "secType": "STK"},
        )
        r.raise_for_status()
        results = r.json()

        if not results:
            raise ValueError(f"No contract found for symbol: {symbol}")

        # Prefer a US-listed stock (NASDAQ, NYSE, ARCA, BATS).
        conid: int | None = None
        for item in results:
            if item.get("description", "").upper() in ("NASDAQ", "NYSE", "ARCA", "BATS"):
                conid = int(item["conid"])
                break
        if conid is None:
            conid = int(results[0]["conid"])

        self._conid_cache[symbol] = conid
        logger.debug("Resolved %s → conid %d", symbol, conid)
        return conid

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _get_account_id(self) -> str:
        r = await self._client.get(f"{self._base_url}/iserver/accounts")
        r.raise_for_status()
        data = r.json()
        accounts = data.get("accounts", data) if isinstance(data, dict) else data
        if not accounts:
            raise RuntimeError("No IBKR accounts found.")
        return accounts[0]

    async def _wait_for_fill(self, order_id: str, order: Order) -> float:
        """Poll /iserver/account/orders until the order is filled (up to 60 s)."""
        for _ in range(12):           # 12 × 5 s = 60 s total
            await asyncio.sleep(5)
            try:
                r = await self._client.get(f"{self._base_url}/iserver/account/orders")
                r.raise_for_status()
                for o in r.json().get("orders", []):
                    if str(o.get("orderId", "")) == order_id:
                        if o.get("status") in ("Filled", "PreSubmitted"):
                            return float(o.get("avgPrice", order.limit_price or 0.0))
            except Exception as exc:
                logger.debug("Order status check failed: %s", exc)

        logger.warning(
            "Order %s fill not confirmed within 60 s; using limit/market price.", order_id
        )
        return order.limit_price or 0.0

    async def _tickle_loop(self) -> None:
        """Keep the Gateway session alive by POSTing /tickle every 60 s."""
        while self._connected:
            await asyncio.sleep(60)
            try:
                await self._client.post(f"{self._base_url}/tickle")
            except Exception as exc:
                logger.warning("Tickle failed: %s", exc)

    @staticmethod
    def _build_order_payload(conid: int, order: Order) -> dict:
        payload: dict = {
            "conid": conid,
            "side": order.side.value,   # "BUY" or "SELL"
            "quantity": order.quantity,
            "tif": "DAY",
        }

        if order.order_type == OrderType.MARKET:
            payload["orderType"] = "MKT"
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("limit_price is required for LIMIT orders.")
            payload["orderType"] = "LMT"
            payload["price"] = order.limit_price
        elif order.order_type == OrderType.STOP:
            if order.stop_price is None:
                raise ValueError("stop_price is required for STOP orders.")
            payload["orderType"] = "STP"
            payload["price"] = order.stop_price
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        return payload
