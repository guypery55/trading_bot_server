import logging
import sys
from pathlib import Path


def configure_logging(log_level: str = "INFO", log_to_file: bool = True) -> None:
    """Configure root logger with console + optional file handler."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_to_file:
        Path("logs").mkdir(exist_ok=True)
        file_handler = logging.FileHandler("logs/trading_bot.log")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=log_level.upper(),
        handlers=handlers,
        force=True,  # override any previously configured handlers
    )

    # Quieten noisy third-party loggers
    logging.getLogger("ib_insync").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
