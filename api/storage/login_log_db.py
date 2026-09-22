"""A record of the daily Zerodha login: whether there was a valid session
each trading day, and when it started.

Kite access tokens die at ~6 AM IST, so a human has to log in once a day.
That cannot be automated away — Zerodha wants a person, and automating it
would mean keeping a broker password and a 2FA seed on this disk. What can
be automated is everything around it: noticing early that today has no
session, opening the login page, and keeping the record of which days had
one. Days without a session are the days 15-minute bars and live tracking
are missing, so the gap is worth seeing rather than discovering later.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "login_log.db"
IST = timezone(timedelta(hours=5, minutes=30))

# One row per IST date. PROMPTED means the check found no session and opened
# the login page; a later success overwrites it for that day.
STATUSES = ("LOGGED_IN", "PROMPTED", "MISSING")

SCHEMA = """
CREATE TABLE IF NOT EXISTS login_log (
    trade_date  TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    issued_at   TEXT,
    user_id     TEXT,
    checked_at  TEXT NOT NULL,
    note        TEXT
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


def record(status: str, issued_at: str | None = None, user_id: str | None = None, note: str | None = None,
           today: date | None = None, db_path: Path | None = None) -> str:
    """Writes today's row. A success is never downgraded: once a day has a
    session, a later check that runs after the next 6 AM reset must not
    rewrite it as missing."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    day = (today or datetime.now(IST).date()).isoformat()
    with connect(db_path) as conn:
        existing = conn.execute("SELECT status FROM login_log WHERE trade_date = ?", (day,)).fetchone()
        if existing and existing["status"] == "LOGGED_IN" and status != "LOGGED_IN":
            return "LOGGED_IN"
        conn.execute("INSERT OR REPLACE INTO login_log VALUES (?,?,?,?,?,?)",
                     (day, status, issued_at, user_id, datetime.now(IST).isoformat(), note))
    return status


def history(limit: int = 30, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM login_log ORDER BY trade_date DESC LIMIT ?", (limit,))]


def summary(db_path: Path | None = None) -> dict:
    rows = history(limit=1000, db_path=db_path)
    logged = [r for r in rows if r["status"] == "LOGGED_IN"]
    streak = 0
    for r in rows:  # newest first
        if r["status"] != "LOGGED_IN":
            break
        streak += 1
    return {
        "days_recorded": len(rows),
        "days_logged_in": len(logged),
        "days_without_a_session": len(rows) - len(logged),
        "current_streak": streak,
        "last_login": logged[0]["trade_date"] if logged else None,
        "last_login_at": logged[0]["issued_at"] if logged else None,
        "recent": rows[:14],
    }
