"""Zerodha Kite Connect provider — same MarketDataProvider interface as
CSVProvider and YFinanceProvider, so nothing above market_data/ changes.

Needs a valid daily session (see kite_session.py). Raises KiteNotLoggedIn
rather than silently falling back to another source: a caller asking for
Zerodha data must know when it didn't get Zerodha data.
"""

import time as _time
from datetime import date, datetime, time, timedelta

from .base import Candle
from .kite_session import IST, authenticated_client

# Kite instrument tokens for the indices this project uses (NSE segment).
INSTRUMENT_TOKENS = {
    "^NSEI": 256265,
    "NIFTY 50": 256265,
    "^NSEBANK": 260105,
    "NIFTY BANK": 260105,
    "^INDIAVIX": 264969,
    "INDIA VIX": 264969,
}

INTERVALS = {
    "1m": "minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "1d": "day",
}

# Kite rejects a single historical request spanning more days than this.
MAX_DAYS_PER_REQUEST = {
    "minute": 60,
    "3minute": 100,
    "5minute": 100,
    "10minute": 100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
    "day": 2000,
}

REQUEST_SPACING_S = 0.35  # historical API allows ~3 requests/second

INTERVAL_MINUTES = {
    "minute": 1, "3minute": 3, "5minute": 5, "10minute": 10,
    "15minute": 15, "30minute": 30, "60minute": 60,
}
MARKET_CLOSE = time(15, 30)


def is_provisional(bar_start: datetime, interval: str, now: datetime) -> bool:
    """A bar is final only once its whole time window has passed. Kite
    returns the in-progress bar alongside completed ones, with a close
    that is really just the latest tick."""
    session_close = datetime.combine(bar_start.date(), MARKET_CLOSE, tzinfo=IST)
    if interval == "day":
        return now < session_close
    bar_end = bar_start + timedelta(minutes=INTERVAL_MINUTES[interval])
    # Cap at 15:30 only for bars inside the regular session: special sessions
    # (Diwali Muhurat at 18:15, the 2021-02-24 outage extension to 16:45)
    # start after it, and capping would mark them final the instant they open.
    if bar_start < session_close:
        bar_end = min(bar_end, session_close)
    return now < bar_end


class ZerodhaProvider:
    def get_ohlc(
        self, symbol: str, timeframe: str, start: date, end: date, now: datetime | None = None
    ) -> list[Candle]:
        if symbol not in INSTRUMENT_TOKENS:
            raise ValueError(f"No Kite instrument token mapped for '{symbol}'. Known: {sorted(INSTRUMENT_TOKENS)}")
        if timeframe not in INTERVALS:
            raise ValueError(f"Unsupported timeframe '{timeframe}'. Choose one of {list(INTERVALS)}.")

        kite = authenticated_client()
        token = INSTRUMENT_TOKENS[symbol]
        interval = INTERVALS[timeframe]
        step = timedelta(days=MAX_DAYS_PER_REQUEST[interval] - 1)

        rows: list[dict] = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + step, end)
            rows.extend(kite.historical_data(token, chunk_start, chunk_end, interval))
            chunk_start = chunk_end + timedelta(days=1)
            if chunk_start <= end:
                _time.sleep(REQUEST_SPACING_S)

        now = now or datetime.now(IST)
        seen: set[str] = set()
        candles: list[Candle] = []
        for r in rows:
            ts: datetime = r["date"]
            stamp = ts.date().isoformat() if interval == "day" else ts.isoformat()
            if stamp in seen:
                continue
            seen.add(stamp)
            candles.append(
                Candle(
                    timestamp=stamp, open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                    volume=r.get("volume"), provisional=is_provisional(ts, interval, now),
                )
            )
        return candles
