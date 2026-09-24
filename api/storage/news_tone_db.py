"""The daily news-tone series, keyed by the frozen query that produced it.

Separate from news.db on purpose. That file is the forward-only headline
archive, written from the day the feature shipped and impossible to rebuild.
This one is a cache of a public dataset: if it were lost it could be fetched
again, so it is not in the nightly backup set and losing it costs time, not
evidence.

`query_set` is part of the key. A reworded query produces a different series
and is stored beside the old one rather than overwriting it, so a result can
always be traced to the exact search that produced it.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "news_tone.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tone (
    query_set  TEXT NOT NULL,
    utc_date   TEXT NOT NULL,
    tone       REAL,
    volume     REAL,
    PRIMARY KEY (query_set, utc_date)
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_tone(query_set: str, rows: list[tuple[str, float]], db_path: Path | None = None) -> int:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT INTO tone (query_set, utc_date, tone) VALUES (?,?,?) "
            "ON CONFLICT(query_set, utc_date) DO UPDATE SET tone = excluded.tone",
            [(query_set, d, v) for d, v in rows])
        return conn.total_changes - before


def save_volume(query_set: str, rows: list[tuple[str, float]], db_path: Path | None = None) -> int:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT INTO tone (query_set, utc_date, volume) VALUES (?,?,?) "
            "ON CONFLICT(query_set, utc_date) DO UPDATE SET volume = excluded.volume",
            [(query_set, d, v) for d, v in rows])
        return conn.total_changes - before


def series(query_set: str, db_path: Path | None = None) -> dict[str, dict]:
    path = db_path or DB_PATH
    if not path.exists():
        return {}
    with connect(db_path) as conn:
        return {r["utc_date"]: {"tone": r["tone"], "volume": r["volume"]}
                for r in conn.execute(
                    "SELECT utc_date, tone, volume FROM tone WHERE query_set = ? ORDER BY utc_date",
                    (query_set,))}


def coverage(query_set: str, db_path: Path | None = None) -> dict:
    path = db_path or DB_PATH
    if not path.exists():
        return {"days": 0, "first": None, "last": None}
    with connect(db_path) as conn:
        r = conn.execute(
            "SELECT COUNT(*) n, MIN(utc_date) a, MAX(utc_date) b FROM tone "
            "WHERE query_set = ? AND tone IS NOT NULL", (query_set,)).fetchone()
        return {"days": r["n"], "first": r["a"], "last": r["b"]}
