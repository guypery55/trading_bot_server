"""Synchronous Telegram helper for use in logging handlers.

For async notification of trade fills, use notifications.telegram_notifier instead.
"""

import os

import httpx

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(text: str) -> bool:
    """Send a plain-text message to the configured Telegram chat.

    Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment
    at call time (not import time) so that .env loading order doesn't matter.

    Returns True on success, False on failure (never raises).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False

    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        response = httpx.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False
