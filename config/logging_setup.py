import logging
import os
import sys
from pathlib import Path

from notifications.telegram_notifier import send_telegram_message


# ── Telegram logging handler ────────────────────────────────────────────────

_LEVEL_EMOJI = {
    logging.INFO: "ℹ️",
    logging.ERROR: "❌",
    logging.CRITICAL: "🚨",
}

_TELEGRAM_LEVELS = {logging.INFO, logging.ERROR, logging.CRITICAL}


class TelegramHandler(logging.Handler):
    """Forwards INFO / ERROR / CRITICAL log records to Telegram."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno not in _TELEGRAM_LEVELS:
            return

        emoji = _LEVEL_EMOJI.get(record.levelno, "")
        message = f"{emoji} <b>[{record.levelname}]</b> {record.getMessage()}"

        if record.exc_info:
            import traceback
            tb = "".join(traceback.format_exception(*record.exc_info))
            message += f"\n<pre>{tb[-1000:]}</pre>"

        send_telegram_message(message)


# ── Public setup function ───────────────────────────────────────────────────

def configure_logging(log_level: str = "INFO", log_to_file: bool = True) -> None:
    """Configure root logger with console + file + optional Telegram handler."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_to_file:
        Path("logs").mkdir(exist_ok=True)
        file_handler = logging.FileHandler("logs/trading_bot.log")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # Add Telegram handler when credentials are configured
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        telegram_handler = TelegramHandler()
        telegram_handler.setLevel(logging.INFO)
        handlers.append(telegram_handler)

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level.upper(),
        handlers=handlers,
        force=True,  # override any previously configured handlers
    )

    # Quieten noisy third-party loggers
    logging.getLogger("ibapi").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
