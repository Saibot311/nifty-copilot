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
