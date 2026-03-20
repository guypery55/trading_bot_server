import logging

import aiosqlite

from broker.order_models import Fill

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fills (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id         TEXT    NOT NULL,
    symbol           TEXT    NOT NULL,
    side             TEXT    NOT NULL,
    filled_quantity  REAL    NOT NULL,
    average_price    REAL    NOT NULL,
    commission       REAL    NOT NULL DEFAULT 0.0,
    timestamp        TEXT    NOT NULL
)
"""

INSERT_FILL_SQL = """
INSERT INTO fills (order_id, symbol, side, filled_quantity, average_price, commission, timestamp)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


class TradeLogger:
    """Persists trade fills to a SQLite database using aiosqlite."""

    def __init__(self, database_url: str = "sqlite:///./trades.db") -> None:
        # Strip the "sqlite:///" prefix if present
        db_path = database_url.replace("sqlite:///", "")
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the database connection and create the fills table if needed."""
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute(CREATE_TABLE_SQL)
        await self._conn.commit()
        logger.info("TradeLogger initialized at: %s", self._db_path)

    async def log_fill(self, fill: Fill) -> None:
        """Insert a fill record into the database."""
        if self._conn is None:
            raise RuntimeError("TradeLogger not initialized. Call init() first.")
        await self._conn.execute(
            INSERT_FILL_SQL,
            (
                fill.order_id,
                fill.symbol,
                fill.side.value,
                fill.filled_quantity,
                fill.average_price,
                fill.commission,
                fill.timestamp.isoformat(),
            ),
        )
        await self._conn.commit()
        logger.debug("Fill logged: %s %s @ %.4f", fill.side.value, fill.symbol, fill.average_price)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("TradeLogger closed.")
