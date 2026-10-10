"""Kronos's forecasts and how each turned out, append-only.

Two kinds: "daily" (the next session's close, written before it opens) and
"live" (the next hour of five-minute candles, written in the session). A
forecast is written before its outcome exists and never changed; the outcome
is written once the target has passed. UPDATE and DELETE are refused.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "kronos.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    kind      TEXT NOT NULL CHECK (kind IN ('daily', 'live')),
    target    TEXT NOT NULL,     -- daily: 'YYYY-MM-DD'; live: the last forecast bar's close, IST ISO
    made_at   TEXT NOT NULL,
    body      TEXT NOT NULL,
    PRIMARY KEY (kind, target)
);
CREATE TABLE IF NOT EXISTS outcomes (
    kind      TEXT NOT NULL,
    target    TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    body      TEXT NOT NULL,
    PRIMARY KEY (kind, target)
);
CREATE TRIGGER IF NOT EXISTS kf_never_updated BEFORE UPDATE ON forecasts BEGIN SELECT RAISE(ABORT, 'a forecast is never edited'); END;
CREATE TRIGGER IF NOT EXISTS kf_never_deleted BEFORE DELETE ON forecasts BEGIN SELECT RAISE(ABORT, 'a forecast is never edited'); END;
CREATE TRIGGER IF NOT EXISTS ko_never_updated BEFORE UPDATE ON outcomes BEGIN SELECT RAISE(ABORT, 'an outcome is never edited'); END;
CREATE TRIGGER IF NOT EXISTS ko_never_deleted BEFORE DELETE ON outcomes BEGIN SELECT RAISE(ABORT, 'an outcome is never edited'); END;
"""


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


def add_forecast(kind: str, target: str, made_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO forecasts VALUES (?, ?, ?, ?)", (kind, target, made_at, json.dumps(body)))
        return conn.total_changes > before


def add_outcome(kind: str, target: str, scored_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO outcomes VALUES (?, ?, ?, ?)", (kind, target, scored_at, json.dumps(body)))
        return conn.total_changes > before


def records(kind: str, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT f.target, f.made_at, f.body AS f, o.scored_at, o.body AS o FROM forecasts f "
                            "LEFT JOIN outcomes o ON o.kind = f.kind AND o.target = f.target WHERE f.kind = ? "
                            "ORDER BY f.target", (kind,)).fetchall()
    return [{"target": r["target"], "made_at": r["made_at"], "forecast": json.loads(r["f"]),
             "scored_at": r["scored_at"], "outcome": json.loads(r["o"]) if r["o"] else None} for r in rows]
