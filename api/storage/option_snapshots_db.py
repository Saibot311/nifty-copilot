"""NIFTY option prices through the session, every five minutes (the strategy
pipeline's Phase 4).

The options archive holds one price per contract per day, so no study here
could see an option's price at 10:30 or at 15:00, and every intraday test
had to model it. Neither NSE nor Kite serves intraday history for contracts
that have expired, so the only way to have it later is to record it now:
last price, bid and ask with their sizes, implied volatility, open interest
and volume, for the nearest expiries, near the money.

Like the forward log, it cannot be rebuilt from anything else once a day has
passed. Rows are only ever added: a snapshot NSE has already given (same
timestamp, expiry, strike and side) is ignored, never overwritten, and
nothing here deletes.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "option_snapshots.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    taken_at     TEXT NOT NULL,     -- NSE's own time for the chain, IST, 'YYYY-MM-DDTHH:MM:SS'
    expiry       TEXT NOT NULL,     -- 'YYYY-MM-DD'
    strike       REAL NOT NULL,
    option_type  TEXT NOT NULL,     -- CE | PE
    spot         REAL,              -- NIFTY in the same chain
    ltp          REAL,              -- missing where NSE has no trade, never zero
    bid          REAL,
    ask          REAL,
    bid_qty      INTEGER,
    ask_qty      INTEGER,
    iv           REAL,
    oi           INTEGER,
    volume       INTEGER,
    PRIMARY KEY (taken_at, expiry, strike, option_type)
);
CREATE TABLE IF NOT EXISTS runs (
    started_at   TEXT PRIMARY KEY,  -- UTC, when this run began
    outcome      TEXT NOT NULL,     -- saved | closed | failed
    rows         INTEGER NOT NULL,
    detail       TEXT
);
"""

COLUMNS = ("taken_at", "expiry", "strike", "option_type", "spot", "ltp", "bid", "ask", "bid_qty", "ask_qty",
           "iv", "oi", "volume")


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save(rows: list[dict], db_path: Path | None = None) -> int:
    """Adds the rows it has not seen; returns how many were new."""
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR IGNORE INTO snapshots ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            [tuple(r.get(c) for c in COLUMNS) for r in rows])
        return conn.total_changes - before


def log_run(outcome: str, rows: int, detail: str = "", db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO runs (started_at, outcome, rows, detail) VALUES (?, ?, ?, ?)",
                     (datetime.now(timezone.utc).isoformat(), outcome, rows, detail[:500]))


def summary(db_path: Path | None = None) -> dict:
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS n, MIN(taken_at) AS first, MAX(taken_at) AS last, "
                           "COUNT(DISTINCT taken_at) AS snapshots FROM snapshots").fetchone()
        return dict(row)
