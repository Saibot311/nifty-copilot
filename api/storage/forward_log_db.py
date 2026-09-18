"""Forward log: what the system recommended each day, recorded *before* the
outcome existed.

This is the one kind of evidence a backtest can't manufacture — every row
was written with no knowledge of what came next. So it is strictly
append-only and write-once per date (INSERT OR IGNORE): a verdict, once
recorded, is never updated, and nothing may ever be backfilled into it —
a "forward" row written after the fact is just a backtest in disguise.
Outcomes are never stored here; they're computed on read from price data.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "forward_log.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS recommendation_log (
    as_of         TEXT PRIMARY KEY,   -- date of the daily close the verdict was based on
    recorded_at   TEXT NOT NULL,      -- UTC wall-clock time the row was written
    action        TEXT NOT NULL,      -- CONSIDER_CALL | CONSIDER_PUT | NO_TRADE
    regime        TEXT NOT NULL,
    close_as_of   REAL NOT NULL,
    headline      TEXT NOT NULL,
    candidates_json   TEXT NOT NULL,
    evidence_bar_json TEXT NOT NULL
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


def record_recommendation(rec: dict, close_as_of: float, db_path: Path | None = None) -> bool:
    """Returns True if a new row was written, False if this date was already recorded."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO recommendation_log
               (as_of, recorded_at, action, regime, close_as_of, headline, candidates_json, evidence_bar_json)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                rec["as_of"],
                datetime.now(timezone.utc).isoformat(),
                rec["action"],
                rec["regime"],
                close_as_of,
                rec.get("headline", ""),
                json.dumps(rec.get("candidates", [])),
                json.dumps(rec.get("evidence_bar", {})),
            ),
        )
        return cur.rowcount == 1


def all_recommendations(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM recommendation_log ORDER BY as_of DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["candidates"] = json.loads(d.pop("candidates_json"))
        d["evidence_bar"] = json.loads(d.pop("evidence_bar_json"))
        out.append(d)
    return out
