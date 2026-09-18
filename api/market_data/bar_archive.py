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
        return [
            Candle(timestamp=r["ts"], open=r["open"], high=r["high"], low=r["low"], close=r["close"], volume=r["volume"])
            for r in rows
        ]
