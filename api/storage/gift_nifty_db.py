"""Nightly snapshots of GIFT Nifty — the only way to build its history,
since NSE IX publishes no free daily file."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "gift_nifty.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    taken_at TEXT PRIMARY KEY, symbol TEXT, expiry TEXT, last REAL, previous_close REAL,
    change_pct REAL, open REAL, high REAL, low REAL, volume REAL, last_trade_time TEXT
);
"""


def save(q: dict, db_path: Path | None = None) -> None:
    conn = sqlite3.connect(db_path or DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (datetime.now(timezone.utc).isoformat(), q["symbol"], q["expiry"], q["last"],
                      q["previous_close"], q["change_pct"], q["open"], q["high"], q["low"], q["volume"],
                      q["last_trade_time"]))
        conn.commit()
    finally:
        conn.close()


def count(db_path: Path | None = None) -> int:
    path = db_path or DB_PATH
    if not path.exists():
        return 0
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        return conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    finally:
        conn.close()
