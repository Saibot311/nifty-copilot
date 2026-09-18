from datetime import date
from typing import Protocol

from pydantic import BaseModel


class Candle(BaseModel):
    timestamp: str  # ISO date or datetime, provider decides granularity
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    # True while the bar's time window hasn't closed yet: its high/low/close
    # can still change. Signals and backtests must never use a provisional bar.
    provisional: bool = False


class MarketDataProvider(Protocol):
    """Every data source (Zerodha, CSV, Yahoo Finance, whatever comes next)
    implements this and nothing else. The rest of the app only ever talks
    to this interface — never to a specific provider directly."""

    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> list[Candle]:
        ...
