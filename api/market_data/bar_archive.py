"""Local SQLite archive of index OHLC bars pulled from Kite, plus a
provider that reads from it.

Why: Kite access tokens die every morning, and ~11.7 years of 15-minute
history is ~22 API requests to re-download. Backtests should run from a
local, fixed copy — reproducible and usable without a login. Same idea as
the options archive, but for index bars.

Only *completed* bars are ever written. A provisional (still-forming) bar
stored here would silently become "history" with a wrong close.
Filled by scripts/backfill_bars.py; the DB file is gitignored (api/data/).
"""

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .base import Candle

DB_PATH = Path(__file__).parent.parent / "data" / "nifty_bars.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_bars (
    symbol   TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts       TEXT NOT NULL,
    open     REAL NOT NULL,
    high     REAL NOT NULL,
    low      REAL NOT NULL,
    close    REAL NOT NULL,
    volume   REAL,
    source   TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, ts)
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_bars(symbol: str, interval: str, candles: list[Candle], source: str, db_path: Path | None = None) -> int:
    """Upserts completed bars; skips provisional ones. Returns rows written."""
    final = [c for c in candles if not c.provisional]
    with connect(db_path) as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO index_bars
               (symbol, interval, ts, open, high, low, close, volume, source)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(symbol, interval, c.timestamp, c.open, c.high, c.low, c.close, c.volume, source) for c in final],
        )
    return len(final)


def last_timestamp(symbol: str, interval: str, db_path: Path | None = None) -> str | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT MAX(ts) FROM index_bars WHERE symbol = ? AND interval = ?", (symbol, interval)
        ).fetchone()
    return row[0]


def archive_summary(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT symbol, interval, COUNT(*) AS bars, MIN(ts) AS first, MAX(ts) AS last,
                      COUNT(DISTINCT substr(ts, 1, 10)) AS days
               FROM index_bars GROUP BY symbol, interval ORDER BY symbol, interval"""
        ).fetchall()
    return [dict(r) for r in rows]


def clamp_to_daily(high: float, low: float, open_: float, close: float,
                   day_high: float, day_low: float) -> tuple[float, float]:
    """An intraday bar cannot trade outside the day's official range. The
    Kite 15-minute archive has a few bad ticks that do — 2022-03-07's 10:00
    bar has open, low and close at 15,785.4 and a high of 16,174.45, 230
    points above anything that traded that day. Clamped here so research and
    charts never see them; open and close are kept inside the bar."""
    high = max(min(high, day_high), open_, close)
    low = min(max(low, day_low), open_, close)
    return high, low


class ArchiveProvider:
    """MarketDataProvider over the local archive — no network, no login."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path

    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> list[Candle]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT ts, open, high, low, close, volume FROM index_bars
                   WHERE symbol = ? AND interval = ? AND substr(ts, 1, 10) BETWEEN ? AND ?
                   ORDER BY ts""",
                (symbol, timeframe, start.isoformat(), end.isoformat()),
            ).fetchall()
        daily = {}
        if timeframe != "1d" and rows:
            with connect(self.db_path) as conn:
                daily = {r["ts"][:10]: (r["high"], r["low"]) for r in conn.execute(
                    """SELECT ts, high, low FROM index_bars WHERE symbol = ? AND interval = '1d'
                       AND ts BETWEEN ? AND ?""", (symbol, start.isoformat(), end.isoformat()))}
        out = []
        for r in rows:
            hi, lo = r["high"], r["low"]
            if r["ts"][:10] in daily:
                hi, lo = clamp_to_daily(hi, lo, r["open"], r["close"], *daily[r["ts"][:10]])
            out.append(Candle(timestamp=r["ts"], open=r["open"], high=hi, low=lo, close=r["close"], volume=r["volume"]))
        return out


def index_trading_days(symbol: str = "^NSEI", db_path: Path | None = None) -> tuple[set[str], str | None]:
    """Every date the index had a daily bar, and the last date archived.

    The options backfill needs to tell a holiday from a failed download, and
    the index is the authority on whether a session happened. Includes the
    weekend sessions NSE occasionally holds (Budget day, Muhurat)."""
    with connect(db_path) as conn:
        days = {r["ts"][:10] for r in conn.execute(
            "SELECT ts FROM index_bars WHERE symbol = ? AND interval = '1d'", (symbol,))}
    return days, (max(days) if days else None)
