from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP = "STP"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Order(BaseModel):
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    limit_price: float | None = None
    stop_price: float | None = None
    client_order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    model_config = {"frozen": True}


class Fill(BaseModel):
    order_id: str
    symbol: str
    side: OrderSide
    filled_quantity: float
    average_price: float
    commission: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class Position(BaseModel):
    symbol: str
    quantity: float
    average_cost: float
    unrealized_pnl: float = 0.0

    model_config = {"frozen": True}


class AccountSummary(BaseModel):
    net_liquidation: float
    buying_power: float
    cash_balance: float
    day_trades_remaining: int = 0

    model_config = {"frozen": True}
