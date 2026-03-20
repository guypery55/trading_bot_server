import logging
import os
from utils.telegram import send_telegram_message

# Emoji prefix per log level for quick scanning in Telegram
LEVEL_EMOJI = {
    logging.INFO: "ℹ️",
    logging.ERROR: "❌",
    logging.CRITICAL: "🚨",
}

# Only forward these levels to Telegram
TELEGRAM_LEVELS = {logging.INFO, logging.ERROR, logging.CRITICAL}


class TelegramHandler(logging.Handler):
    """Logging handler that forwards selected log levels to Telegram."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno not in TELEGRAM_LEVELS:
            return

        emoji = LEVEL_EMOJI.get(record.levelno, "")
        message = (
            f"{emoji} <b>[{record.levelname}]</b> {record.getMessage()}"
        )

        if record.exc_info:
            import traceback
            tb = "".join(traceback.format_exception(*record.exc_info))
            message += f"\n<pre>{tb[-1000:]}</pre>"  # cap at 1000 chars

        send_telegram_message(message)


def get_logger(name: str = "trading_bot") -> logging.Logger:
    """Return a logger with both console and Telegram handlers attached."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Console handler — all levels
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # Telegram handler — INFO, ERROR, CRITICAL only
    telegram_handler = TelegramHandler()
    telegram_handler.setLevel(logging.INFO)
    logger.addHandler(telegram_handler)

    return logger
