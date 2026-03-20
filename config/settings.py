from enum import Enum
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class ConnectionType(str, Enum):
    TWS = "tws"
    GATEWAY = "gateway"


# Default IBKR ports per mode + connection type
_IBKR_PORTS: dict[TradingMode, dict[ConnectionType, int]] = {
    TradingMode.PAPER: {ConnectionType.TWS: 7497, ConnectionType.GATEWAY: 4002},
    TradingMode.LIVE:  {ConnectionType.TWS: 7496, ConnectionType.GATEWAY: 4001},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        frozen=True,
        extra="ignore",
    )

    # IBKR connection
    ibkr_host: str = "127.0.0.1"
    ibkr_connection_type: ConnectionType = ConnectionType.TWS
    ibkr_port: int | None = None          # None = auto-derive from mode + connection_type
    ibkr_client_id: int = 1

    # Trading
    trading_mode: TradingMode = TradingMode.PAPER
    symbol: str = "AAPL"
    bar_size: str = "5 mins"
    strategy: str = "rsi_macd"

    # Logging
    log_level: str = "INFO"

    # Notifications (optional)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @model_validator(mode="after")
    def resolve_port(self) -> "Settings":
        """Auto-derive IBKR port from trading_mode + connection_type if not set explicitly."""
        if self.ibkr_port is None:
            derived = _IBKR_PORTS[self.trading_mode][self.ibkr_connection_type]
            # Pydantic frozen models don't allow assignment — use object.__setattr__
            object.__setattr__(self, "ibkr_port", derived)
        return self

    @property
    def notifications_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_settings() -> Settings:
    return Settings()
