"""Telegram helpers — sync logging helper + async notifier for trade alerts."""

import logging
import os

import httpx

from broker.order_models import Fill

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


# ── Sync helper (used by the logging handler) ───────────────────────────────

def send_telegram_message(text: str) -> bool:
    """Send a message synchronously. Reads credentials from env at call time.

    Returns True on success, False on failure (never raises).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False

    url = TELEGRAM_API_URL.format(token=token)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        response = httpx.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False

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
