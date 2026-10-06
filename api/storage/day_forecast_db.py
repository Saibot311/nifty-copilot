"""The day-ahead forecasts and how each turned out.

A forecast is written before its session (by the nightly job, or the first
evening after a close) and never changed; its outcome is written once the
session's close is in the daily archive. The database refuses UPDATE and
DELETE, like the forward log: a forecast that could be edited after the
fact would prove nothing.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "day_forecast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    target_day   TEXT PRIMARY KEY,   -- the session forecast, 'YYYY-MM-DD'
    made_at      TEXT NOT NULL,      -- IST, before the session opened
    body         TEXT NOT NULL       -- JSON: inputs, bands, lean, calibration used
);
CREATE TABLE IF NOT EXISTS outcomes (
    target_day   TEXT PRIMARY KEY REFERENCES forecasts(target_day),
    scored_at    TEXT NOT NULL,
    body         TEXT NOT NULL       -- JSON: the session's bar, z, hits, reasons
);
-- Which method sized the band from each close on (briefing/forecast_learning):
-- the scores it was chosen on and whether it replaced the one before.
CREATE TABLE IF NOT EXISTS method_choices (
    decided_on   TEXT PRIMARY KEY,   -- the close the choice was made after
    made_at      TEXT NOT NULL,
    body         TEXT NOT NULL       -- JSON: champion, previous, switched, scores, halves, reason
);
CREATE TRIGGER IF NOT EXISTS method_choices_never_updated BEFORE UPDATE ON method_choices
BEGIN SELECT RAISE(ABORT, 'a method choice is never edited'); END;
CREATE TRIGGER IF NOT EXISTS method_choices_never_deleted BEFORE DELETE ON method_choices
BEGIN SELECT RAISE(ABORT, 'a method choice is never edited'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_never_updated BEFORE UPDATE ON forecasts
BEGIN SELECT RAISE(ABORT, 'a forecast is never edited'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_never_deleted BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'a forecast is never edited'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_never_updated BEFORE UPDATE ON outcomes
BEGIN SELECT RAISE(ABORT, 'an outcome is never edited'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_never_deleted BEFORE DELETE ON outcomes
BEGIN SELECT RAISE(ABORT, 'an outcome is never edited'); END;
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


def add_forecast(target_day: str, made_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO forecasts VALUES (?, ?, ?)", (target_day, made_at, json.dumps(body)))
        return conn.total_changes > before


def add_outcome(target_day: str, scored_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO outcomes VALUES (?, ?, ?)", (target_day, scored_at, json.dumps(body)))
        return conn.total_changes > before


def records(db_path: Path | None = None) -> list[dict]:
    """Every forecast, oldest first, with its outcome when scored."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT f.target_day, f.made_at, f.body AS f, o.scored_at, o.body AS o FROM forecasts f "
                            "LEFT JOIN outcomes o USING (target_day) ORDER BY f.target_day").fetchall()
    return [{"target_day": r["target_day"], "made_at": r["made_at"], "forecast": json.loads(r["f"]),
             "scored_at": r["scored_at"], "outcome": json.loads(r["o"]) if r["o"] else None} for r in rows]


def add_method_choice(decided_on: str, made_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO method_choices VALUES (?, ?, ?)", (decided_on, made_at, json.dumps(body)))
        return conn.total_changes > before


def method_choices(db_path: Path | None = None) -> list[dict]:
    """Every night's choice of method, oldest first."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT decided_on, made_at, body FROM method_choices ORDER BY decided_on").fetchall()
    return [{"decided_on": r["decided_on"], "made_at": r["made_at"], "choice": json.loads(r["body"])} for r in rows]
