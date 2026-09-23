"""Phase 14 — paper observation: hypothetical option positions at real
premiums, opened forward and never backfilled.

Why it exists: the recommendation says NO TRADE almost every day, so the
forward log accrues a verdict and little else. Meanwhile 19 patterns have a
tested option setup that history rejected. Running those setups forward, on
live premiums, with no money, is the one kind of evidence left that a
backtest cannot flatter: nothing here was chosen with knowledge of what
happened next, because it has not happened yet.

Zero execution. No order ever reaches a broker; these rows are a record of
what would have happened, priced from NSE's own end-of-day file.

Like the forward log, a row may only be written for a session that has just
closed — never for a past date. A backfilled "paper trade" is a backtest
wearing a disguise.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "paper.db"
IST = timezone(timedelta(hours=5, minutes=30))

# 'pattern' = a setup that formed. 'control' = the same kind of option bought
# on a fixed schedule with no signal, so the comparison exists forward too.
SOURCES = ("pattern", "control")

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at     TEXT NOT NULL,      -- when this row was written (UTC)
    source        TEXT NOT NULL,      -- pattern | control
    strategy      TEXT NOT NULL,      -- pattern name, or 'control'
    label         TEXT NOT NULL,
    signal_date   TEXT NOT NULL,      -- the close the setup formed on
    underlying    TEXT NOT NULL,
    option_type   TEXT NOT NULL,      -- CE | PE, always bought
    strike        REAL NOT NULL,
    expiry        TEXT NOT NULL,
    entry_date    TEXT NOT NULL,      -- the session after the signal
    entry_premium REAL NOT NULL,
    hold_days     INTEGER NOT NULL,
    planned_exit  TEXT,               -- filled once the session is known
    exit_date     TEXT,
    exit_premium  REAL,
    mark_date     TEXT,               -- last mark-to-market
    mark_premium  REAL,
    status        TEXT NOT NULL,      -- OPEN | CLOSED
    UNIQUE (strategy, signal_date, source)
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


def open_position(row: dict, db_path: Path | None = None) -> bool:
    """Writes one open position. False if that setup already has one for
    that signal date — a pattern forming again mid-hold does not stack."""
    cols = ("source", "strategy", "label", "signal_date", "underlying", "option_type", "strike", "expiry",
            "entry_date", "entry_premium", "hold_days", "planned_exit")
    with connect(db_path) as conn:
        cur = conn.execute(
            f"INSERT OR IGNORE INTO paper_trades (opened_at, status, {', '.join(cols)}) "
            f"VALUES (?, 'OPEN'{', ?' * len(cols)})",
            (datetime.now(timezone.utc).isoformat(), *(row.get(c) for c in cols)))
        return cur.rowcount == 1


def set_planned_exit(trade_id: int, planned_exit: str, db_path: Path | None = None) -> None:
    """The exit session is not on the calendar yet when a position opens, so
    it is filled in once it is. A schedule, not an outcome."""
    with connect(db_path) as conn:
        conn.execute("UPDATE paper_trades SET planned_exit = ? WHERE id = ? AND planned_exit IS NULL",
                     (planned_exit, trade_id))


def mark(trade_id: int, mark_date: str, premium: float, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE paper_trades SET mark_date = ?, mark_premium = ? WHERE id = ? AND status = 'OPEN'",
                     (mark_date, premium, trade_id))


def close_position(trade_id: int, exit_date: str, premium: float, db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("""UPDATE paper_trades SET status = 'CLOSED', exit_date = ?, exit_premium = ?,
                        mark_date = ?, mark_premium = ? WHERE id = ?""",
                     (exit_date, premium, exit_date, premium, trade_id))


def open_trades(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY entry_date")]


def all_trades(limit: int = 500, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM paper_trades ORDER BY signal_date DESC, id DESC LIMIT ?", (limit,))]


def has_signal_date(strategy: str, signal_date: str, source: str, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM paper_trades WHERE strategy = ? AND signal_date = ? AND source = ?",
            (strategy, signal_date, source)).fetchone() is not None
