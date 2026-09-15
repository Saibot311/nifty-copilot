"""Local SQLite archive of NIFTY option bars.

This is the first thing in the project that genuinely needs a database:
backfilling years of per-strike option history means millions of rows that
have to be queried by (date, expiry, strike) during backtests. Holding
that in memory or re-downloading per query would be the wrong shape.

The ingested_days table makes backfill resumable — a multi-thousand-file
download will get interrupted, and re-running should pick up where it
stopped rather than starting over.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from market_data.nse_bhavcopy import OptionBar

DB_PATH = Path(__file__).parent.parent / "data" / "nifty_options.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS option_bars (
    trade_date   TEXT NOT NULL,
    expiry_date  TEXT NOT NULL,
    strike       REAL NOT NULL,
    option_type  TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    settle_price REAL,
    contracts    REAL,
    open_interest REAL,
    change_in_oi REAL,
    PRIMARY KEY (trade_date, expiry_date, strike, option_type)
);
CREATE INDEX IF NOT EXISTS idx_option_bars_trade_date ON option_bars(trade_date);
CREATE INDEX IF NOT EXISTS idx_option_bars_expiry ON option_bars(expiry_date);

CREATE TABLE IF NOT EXISTS ingested_days (
    trade_date  TEXT PRIMARY KEY,
    row_count   INTEGER NOT NULL,
    ingested_at TEXT NOT NULL
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def is_day_ingested(trade_date: str, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM ingested_days WHERE trade_date = ?", (trade_date,)
        ).fetchone()
        return row is not None


def save_day(trade_date: str, bars: list[OptionBar], db_path: Path | None = None) -> int:
    """Stores a day's bars and marks the day ingested. A day with zero bars
    (holiday/weekend) is still marked, so backfill doesn't retry it forever."""
    with connect(db_path) as conn:
        if bars:
            conn.executemany(
                """INSERT OR REPLACE INTO option_bars
                   (trade_date, expiry_date, strike, option_type, open, high, low,
                    close, settle_price, contracts, open_interest, change_in_oi)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(b.trade_date, b.expiry_date, b.strike, b.option_type, b.open, b.high,
                  b.low, b.close, b.settle_price, b.contracts, b.open_interest,
                  b.change_in_oi) for b in bars],
            )
        conn.execute(
            "INSERT OR REPLACE INTO ingested_days (trade_date, row_count, ingested_at) VALUES (?,?,?)",
            (trade_date, len(bars), datetime.now(timezone.utc).isoformat()),
        )
    return len(bars)


def archive_stats(db_path: Path | None = None) -> dict:
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS bars,
                      MIN(trade_date) AS first_date,
                      MAX(trade_date) AS last_date,
                      COUNT(DISTINCT trade_date) AS days
               FROM option_bars"""
        ).fetchone()
        ingested = conn.execute("SELECT COUNT(*) AS n FROM ingested_days").fetchone()
        return {
            "option_bars": row["bars"] or 0,
            "trading_days_with_data": row["days"] or 0,
            "days_checked": ingested["n"] or 0,
            "first_date": row["first_date"],
            "last_date": row["last_date"],
        }


def chain_on_date(trade_date: str, db_path: Path | None = None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM option_bars WHERE trade_date = ? ORDER BY expiry_date, strike, option_type",
            (trade_date,),
        ).fetchall()


def option_price(
    trade_date: str, expiry_date: str, strike: float, option_type: str,
    db_path: Path | None = None,
) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute(
            """SELECT * FROM option_bars
               WHERE trade_date = ? AND expiry_date = ? AND strike = ? AND option_type = ?""",
            (trade_date, expiry_date, strike, option_type),
        ).fetchone()


def expiries_available(trade_date: str, db_path: Path | None = None) -> list[str]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT expiry_date FROM option_bars WHERE trade_date = ? ORDER BY expiry_date",
            (trade_date,),
        ).fetchall()
        return [r["expiry_date"] for r in rows]
