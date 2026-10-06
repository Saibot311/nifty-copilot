"""The sentinel's record of what broke, what was tried, and when it cleared
(api/sentinel/). An incident is written once; everything after it is an
event appended to it — seen again, a repair and its result, an alert sent,
resolved. The database refuses UPDATE and DELETE, like the forward log: the
record of a failure cannot be tidied after the fact."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "incidents.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id         INTEGER PRIMARY KEY,
    check_key  TEXT NOT NULL,
    area       TEXT NOT NULL,
    severity   TEXT NOT NULL,
    opened_at  TEXT NOT NULL,
    summary    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    incident_id INTEGER NOT NULL REFERENCES incidents(id),
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('seen', 'repair', 'alert', 'resolved')),
    detail      TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS incidents_never_updated BEFORE UPDATE ON incidents
BEGIN SELECT RAISE(ABORT, 'incidents are never edited'); END;
CREATE TRIGGER IF NOT EXISTS incidents_never_deleted BEFORE DELETE ON incidents
BEGIN SELECT RAISE(ABORT, 'incidents are never edited'); END;
CREATE TRIGGER IF NOT EXISTS events_never_updated BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'incidents are never edited'); END;
CREATE TRIGGER IF NOT EXISTS events_never_deleted BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'incidents are never edited'); END;
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


def open_incident(check_key: str, area: str, severity: str, summary: str, at: str, db_path: Path | None = None) -> int:
    with connect(db_path) as conn:
        return conn.execute("INSERT INTO incidents (check_key, area, severity, opened_at, summary) VALUES (?, ?, ?, ?, ?)",
                            (check_key, area, severity, at, summary)).lastrowid


def add_event(incident_id: int, kind: str, detail: str, at: str, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("INSERT INTO events (incident_id, at, kind, detail) VALUES (?, ?, ?, ?)",
                     (incident_id, at, kind, detail))


def _with_events(conn, rows) -> list[dict]:
    out = []
    for r in rows:
        ev = [dict(e) for e in conn.execute("SELECT at, kind, detail FROM events WHERE incident_id = ? ORDER BY id",
                                            (r["id"],))]
        seen = [e for e in ev if e["kind"] == "seen"]
        alerts = [e for e in ev if e["kind"] == "alert"]
        done = [e for e in ev if e["kind"] == "resolved"]
        out.append({**dict(r), "seen_count": len(seen), "last_seen": seen[-1]["at"] if seen else r["opened_at"],
                    "repairs": [e for e in ev if e["kind"] == "repair"],
                    "last_alert_at": alerts[-1]["at"] if alerts else None,
                    "resolved_at": done[-1]["at"] if done else None})
    return out


def open_incidents(db_path: Path | None = None) -> list[dict]:
    """Incidents with no 'resolved' event, oldest first."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM incidents WHERE id NOT IN "
                            "(SELECT incident_id FROM events WHERE kind = 'resolved') ORDER BY id").fetchall()
        return _with_events(conn, rows)


def recent(days: int = 14, db_path: Path | None = None, now: str | None = None) -> list[dict]:
    """Every incident opened in the last `days`, open or resolved, newest first."""
    since = (datetime.fromisoformat(now) if now else datetime.now().astimezone()) - timedelta(days=days)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM incidents WHERE opened_at >= ? ORDER BY id DESC",
                            (since.isoformat(timespec="seconds"),)).fetchall()
        return _with_events(conn, rows)
