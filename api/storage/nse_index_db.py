"""Local archive of NSE's daily all-index report (market_data/nse_indices.py)."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_data.nse_indices import INDEX_NAMES, IndexDay, load_archive  # noqa: F401

DB_PATH = Path(__file__).parent.parent / "data" / "nse_indices.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_daily (
    index_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL NOT NULL,
    PRIMARY KEY (index_name, trade_date)
);
CREATE TABLE IF NOT EXISTS fetched_days (
    trade_date TEXT PRIMARY KEY,
    rows INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_day(trade_date: str, rows: list[IndexDay], db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executemany("INSERT OR REPLACE INTO index_daily VALUES (?,?,?,?,?,?)",
                         [(r.index_name, r.trade_date, r.open, r.high, r.low, r.close) for r in rows])
        conn.execute("INSERT OR REPLACE INTO fetched_days VALUES (?,?,?)",
                     (trade_date, len(rows), datetime.now(timezone.utc).isoformat()))


def fetched(db_path: Path | None = None) -> set[str]:
    with connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT trade_date FROM fetched_days")}


def load(underlying: str, db_path: Path | None = None) -> pd.DataFrame:
    """Daily bars for an option underlying ('NIFTY', 'BANKNIFTY', 'MIDCPNIFTY').
    One reader, in the data layer — this delegates so both cannot drift."""
    return load_archive(underlying, db_path or DB_PATH)
