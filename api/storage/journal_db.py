"""Phase 13 — the trade journal: what the user actually did, next to what
the system said that day.

The forward log records the system's verdict before the outcome; this
records the user's decision. Together they answer the question neither can
alone: does following the system, or overriding it, do better? Like the
forward log, it cannot be rebuilt from anything else — it is backed up with it.

Profit and loss is computed here (I2), never typed in: the user enters the
premiums and quantity they actually traded, and costs come from the same
options cost model as every backtest.
"""

import sqlite3

from .sqlite_open import open_db
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "journal.db"

DECISIONS = ("TOOK", "SKIPPED", "WAITED")
UNDERLYINGS = ("NIFTY", "BANKNIFTY", "SENSEX", "MIDCPNIFTY")

SCHEMA = """
CREATE TABLE IF NOT EXISTS journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    trade_date      TEXT NOT NULL,     -- the session the decision was about
    system_action   TEXT,              -- what the system said for that session, looked up, never typed
    decision        TEXT NOT NULL,     -- TOOK | SKIPPED | WAITED
    underlying      TEXT,
    option_type     TEXT,              -- CE | PE (a bought option; this user only buys)
    strike          REAL,
    expiry          TEXT,
    quantity        INTEGER,           -- units, not lots, so lot-size changes never matter
    entry_premium   REAL,
    exit_premium    REAL,
    exit_date       TEXT,
    reason          TEXT,
    notes           TEXT
);
"""


# Columns added after the table first shipped: (name, type). Added with ALTER
# TABLE, which leaves every existing row as it was, with the new fields empty.
# The stop and target are the user's own exit plan for an open trade: the
# page says when the price reaches one, and never sets them itself. exit_kind
# is 'settled' for a trade held to expiry (no sale: it settles at the index's
# close), and empty for a sale.
ADDED_COLUMNS = (("stop_premium", "REAL"), ("target_premium", "REAL"), ("exit_kind", "TEXT"))


def _migrate(conn) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(journal)")}
    for name, kind in ADDED_COLUMNS:
        if name not in have:
            conn.execute(f"ALTER TABLE journal ADD COLUMN {name} {kind}")


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add(entry: dict, db_path: Path | None = None) -> int:
    cols = ("trade_date", "system_action", "decision", "underlying", "option_type", "strike", "expiry",
            "quantity", "entry_premium", "exit_premium", "exit_date", "reason", "notes")
    with connect(db_path) as conn:
        cur = conn.execute(
            f"INSERT INTO journal (created_at, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
            (datetime.now(timezone.utc).isoformat(), *(entry.get(c) for c in cols)))
        return int(cur.lastrowid)


def close(entry_id: int, exit_premium: float, exit_date: str, db_path: Path | None = None,
          exit_kind: str | None = None) -> bool:
    with connect(db_path) as conn:
        # Open trades only: closing a finished trade again used to replace its
        # exit price. A wrong exit is corrected by deleting the entry and
        # adding it again, which leaves a visible record of the change.
        cur = conn.execute("UPDATE journal SET exit_premium = ?, exit_date = ?, exit_kind = ? "
                           "WHERE id = ? AND decision = 'TOOK' AND exit_premium IS NULL",
                           (exit_premium, exit_date, exit_kind, entry_id))
        return cur.rowcount == 1


def set_plan(entry_id: int, stop_premium: float | None, target_premium: float | None,
             db_path: Path | None = None) -> bool:
    """The user's stop and target for an open trade; None clears one."""
    with connect(db_path) as conn:
        cur = conn.execute("UPDATE journal SET stop_premium = ?, target_premium = ? "
                           "WHERE id = ? AND decision = 'TOOK' AND exit_premium IS NULL",
                           (stop_premium, target_premium, entry_id))
        return cur.rowcount == 1


def get(entry_id: int, db_path: Path | None = None) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def delete(entry_id: int, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,)).rowcount == 1


def all_entries(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM journal ORDER BY trade_date DESC, id DESC")]