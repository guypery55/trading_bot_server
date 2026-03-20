"""Async Telegram notifier for trade alerts and bot status updates."""

import logging

import httpx

from broker.order_models import Fill

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

# Emoji per order side for quick scanning
_SIDE_EMOJI = {"BUY": "🟢", "SELL": "🔴"}


class TelegramNotifier:
    """Sends trade notifications to a Telegram chat via the Bot API.

    Uses httpx.AsyncClient for non-blocking HTTP calls so it never
    stalls the trading loop.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._url = TELEGRAM_API_URL.format(token=bot_token)
        self._chat_id = chat_id
        self._client = httpx.AsyncClient(timeout=10)

    async def send_message(self, text: str) -> bool:
        """Send a raw text message. Returns True on success."""
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            resp = await self._client.post(self._url, json=payload)
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False

    async def send_fill_alert(self, fill: Fill) -> None:
        """Format and send a trade fill notification."""
        emoji = _SIDE_EMOJI.get(fill.side.value, "⚪")
        pnl_note = ""
        text = (
            f"{emoji} <b>{fill.side.value}</b> {fill.filled_quantity} x "
            f"<b>{fill.symbol}</b> @ {fill.average_price:.4f}\n"
            f"Commission: ${fill.commission:.2f}{pnl_note}\n"
            f"Order ID: <code>{fill.order_id}</code>"
        )
        await self.send_message(text)

    async def send_status(self, message: str) -> None:
        """Send a general bot status message (start, stop, error, etc.)."""
        await self.send_message(f"ℹ️ <b>Bot Status</b>\n{message}")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
