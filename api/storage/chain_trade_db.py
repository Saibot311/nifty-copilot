"""The option-chain trade's suggestions, append-only (options/chain_trade.py).

The first trade the default rules suggest in each session, written while the
market is open and before its outcome exists, never changed. Scoring it is
left for later; the record is what makes that possible. UPDATE and DELETE are
refused.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "chain_trade.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS suggestions (
    session   TEXT PRIMARY KEY,  -- 'YYYY-MM-DD', IST
    made_at   TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ct_never_updated BEFORE UPDATE ON suggestions BEGIN SELECT RAISE(ABORT, 'a suggestion is never edited'); END;
CREATE TRIGGER IF NOT EXISTS ct_never_deleted BEFORE DELETE ON suggestions BEGIN SELECT RAISE(ABORT, 'a suggestion is never edited'); END;
-- How a locked trade ended: at most one per session, never changed.
CREATE TABLE IF NOT EXISTS exits (
    session   TEXT PRIMARY KEY,
    at        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS cx_never_updated BEFORE UPDATE ON exits BEGIN SELECT RAISE(ABORT, 'an exit is never edited'); END;
CREATE TRIGGER IF NOT EXISTS cx_never_deleted BEFORE DELETE ON exits BEGIN SELECT RAISE(ABORT, 'an exit is never edited'); END;
-- Every look for a trade while the session had none locked.
CREATE TABLE IF NOT EXISTS scans (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    session   TEXT NOT NULL,
    at        TEXT NOT NULL,
    action    TEXT NOT NULL,
    reason    TEXT
);
CREATE TRIGGER IF NOT EXISTS cs_never_updated BEFORE UPDATE ON scans BEGIN SELECT RAISE(ABORT, 'a scan is never edited'); END;
CREATE TRIGGER IF NOT EXISTS cs_never_deleted BEFORE DELETE ON scans BEGIN SELECT RAISE(ABORT, 'a scan is never edited'); END;
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


def add_suggestion(session: str, made_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO suggestions VALUES (?, ?, ?)", (session, made_at, json.dumps(body)))
        return conn.total_changes > before


def suggestions(limit: int = 20, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT session, made_at, body FROM suggestions ORDER BY session DESC LIMIT ?",
                            (limit,)).fetchall()
    return [{"session": r["session"], "made_at": r["made_at"], **json.loads(r["body"])} for r in rows]


def suggestion_for(session: str, db_path: Path | None = None) -> dict | None:
    """The session's locked trade as it was written, or None."""
    with connect(db_path) as conn:
        r = conn.execute("SELECT session, made_at, body FROM suggestions WHERE session = ?", (session,)).fetchone()
    return {"session": r["session"], "made_at": r["made_at"], **json.loads(r["body"])} if r else None


def add_exit(session: str, at: str, kind: str, body: dict, db_path: Path | None = None) -> bool:
    """The session's one exit; a second is ignored."""
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO exits VALUES (?, ?, ?, ?)", (session, at, kind, json.dumps(body)))
        return conn.total_changes > before


def unclosed_before(session: str, db_path: Path | None = None) -> list[str]:
    """Earlier sessions whose locked trade has no exit."""
    with connect(db_path) as conn:
        rows = conn.execute("SELECT s.session FROM suggestions s LEFT JOIN exits e ON e.session = s.session "
                            "WHERE e.session IS NULL AND s.session < ?", (session,)).fetchall()
    return [r["session"] for r in rows]


def exit_for(session: str, db_path: Path | None = None) -> dict | None:
    with connect(db_path) as conn:
        r = conn.execute("SELECT session, at, kind, body FROM exits WHERE session = ?", (session,)).fetchone()
    return {"session": r["session"], "at": r["at"], "kind": r["kind"], **json.loads(r["body"])} if r else None


def add_scan(session: str, at: str, action: str, reason: str | None, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("INSERT INTO scans (session, at, action, reason) VALUES (?, ?, ?, ?)", (session, at, action, reason))


def last_scan(session: str, db_path: Path | None = None) -> dict | None:
    with connect(db_path) as conn:
        r = conn.execute("SELECT at, action, reason FROM scans WHERE session = ? ORDER BY id DESC LIMIT 1",
                         (session,)).fetchone()
    return dict(r) if r else None
