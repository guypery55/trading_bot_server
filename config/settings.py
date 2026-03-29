from __future__ import annotations

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        frozen=True,
        extra="ignore",
    )

    # IBKR Web API (Client Portal Gateway)
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 5000           # CP Gateway default port
    ibkr_client_id: int = 1         # unused by Web API, kept for .env compatibility

    # Trading
    trading_mode: TradingMode = TradingMode.PAPER
    symbols: str = "AAPL"           # comma-separated — use .symbol_list for a list
    bar_size: str = "5 mins"
    strategy: str = "swing"

    # Risk
    daily_spend_limit: float = 1000.0   # max $ traded per day across all symbols
    daily_loss_limit: float = 500.0     # halt trading if daily P&L drops below -this

    # Logging
    log_level: str = "INFO"

    # Notifications (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def symbol_list(self) -> list[str]:
        """Return symbols as a list, split on commas."""
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def notifications_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_settings() -> Settings:
    return Settings()
