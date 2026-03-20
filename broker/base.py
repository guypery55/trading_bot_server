from abc import ABC, abstractmethod
from .order_models import Order, Fill, Position, AccountSummary


class BrokerInterface(ABC):
    """Abstract broker interface. All broker implementations must satisfy this contract."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the broker connection."""
        ...

    @abstractmethod
    async def place_order(self, order: Order) -> Fill:
        """Submit an order and return the resulting fill."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        """Cancel an open order by its ID."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""
        ...

    @abstractmethod
    async def get_account_summary(self) -> AccountSummary:
        """Return a snapshot of the account (equity, buying power, cash)."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the broker connection is active."""
        ...
