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

from .sqlite_open import open_db
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "paper.db"
IST = timezone(timedelta(hours=5, minutes=30))

# 'pattern' = a setup that formed. 'best_read' = the one taken when nothing
# formed. 'control' = the same kind of option bought on a fixed schedule with
# no signal, so the comparison exists forward too.
SOURCES = ("pattern", "best_read", "control")

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
    lots          INTEGER NOT NULL DEFAULT 1,
    entry_cost_rs REAL NOT NULL DEFAULT 0,
    exit_cost_rs  REAL,
    -- 1 = a position in the book: it spends allocated cash and moves equity.
    -- 0 = a yardstick: priced on the same real premiums, but outside the
    -- book, because the book takes one position a session and a benchmark
    -- must not be able to take that slot.
    funded        INTEGER NOT NULL DEFAULT 1,
    cost_model    TEXT,               -- NULL: round trip at entry (pre 2026-09-24); 'split': each leg on its premium
    UNIQUE (strategy, signal_date, source)
);

-- What each evening decided, and why — including what it did not do. The
-- reasons used to be computed and thrown away, so an empty book looked the
-- same as a quiet market. Appended every run; never edited.
CREATE TABLE IF NOT EXISTS paper_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at        TEXT NOT NULL,      -- UTC
    entry_date    TEXT,
    signal_date   TEXT,
    decision_json TEXT NOT NULL
);

-- Money the user has allocated to the paper book, and nothing else. A
-- deposit is a row; the balance is their sum. Positions are sized against
-- it, so a paper book cannot spend money that was never allocated.
CREATE TABLE IF NOT EXISTS paper_funds (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    amount  REAL NOT NULL,
    note    TEXT
);
"""

# Columns added after the table first shipped.
_MIGRATIONS = (
    ("lots", "INTEGER NOT NULL DEFAULT 1"),
    ("entry_cost_rs", "REAL NOT NULL DEFAULT 0"),
    ("exit_cost_rs", "REAL"),
    ("funded", "INTEGER NOT NULL DEFAULT 1"),
    # NULL: the whole round trip was charged at entry (rows before
    # 2026-09-24). 'split': each leg on its own premium.
    ("cost_model", "TEXT"),
)


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        have = {r["name"] for r in conn.execute("PRAGMA table_info(paper_trades)")}
        added = []
        for name, decl in _MIGRATIONS:
            if name not in have:
                conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {name} {decl}")
                added.append(name)
        # One funded position per entry session, held by the table rather than
        # by the caller alone: two runs at once could otherwise both see an
        # empty session and both open. Skipped, not fatal, if old rows ever
        # broke the rule — the book must still load.
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_funded_position_a_session "
                         "ON paper_trades (entry_date) WHERE funded = 1")
        except sqlite3.IntegrityError:
            pass
        if "funded" in added:
            # The control used to be a funded position, and two of them — a
            # call and a put — could be the whole of a session's activity.
            # The book now takes one position a session, so the yardstick
            # moves outside it. The rows are not touched: they keep their
            # premiums, their dates and their marks, and only stop counting
            # as money. Nothing is deleted; a paper trade that happened
            # happened.
            conn.execute("UPDATE paper_trades SET funded = 0 WHERE source = 'control'")
        yield conn
        conn.commit()
    finally:
        conn.close()


def open_position(row: dict, db_path: Path | None = None) -> bool:
    """Writes one open position. False if that setup already has one for
    that signal date — a pattern forming again mid-hold does not stack."""
    cols = ("source", "strategy", "label", "signal_date", "underlying", "option_type", "strike", "expiry",
            "entry_date", "entry_premium", "hold_days", "planned_exit", "lots", "entry_cost_rs", "funded",
            "cost_model")
    row = {"lots": 1, "entry_cost_rs": 0.0, "funded": 1, **row}
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


def close_position(trade_id: int, exit_date: str, premium: float, exit_cost_rs: float = 0.0,
                   db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.execute("""UPDATE paper_trades SET status = 'CLOSED', exit_date = ?, exit_premium = ?,
                        mark_date = ?, mark_premium = ?, exit_cost_rs = ? WHERE id = ?""",
                     (exit_date, premium, exit_date, premium, exit_cost_rs, trade_id))


# --- the allocated funds -------------------------------------------------------

def add_funds(amount: float, note: str | None = None, db_path: Path | None = None) -> float:
    """A deposit (or a withdrawal, negative). Returns the new balance."""
    from datetime import datetime as _dt
    with connect(db_path) as conn:
        conn.execute("INSERT INTO paper_funds (ts, amount, note) VALUES (?,?,?)",
                     (_dt.now(timezone.utc).isoformat(), float(amount), note))
    return allocated(db_path)


def allocated(db_path: Path | None = None) -> float:
    with connect(db_path) as conn:
        return float(conn.execute("SELECT COALESCE(SUM(amount), 0) FROM paper_funds").fetchone()[0])


def fund_flows(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM paper_funds ORDER BY id DESC LIMIT 50")]


def open_trades(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM paper_trades WHERE status = 'OPEN' ORDER BY entry_date")]


def all_trades(limit: int = 500, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM paper_trades ORDER BY signal_date DESC, id DESC LIMIT ?", (limit,))]


def record_decision(decision: dict, db_path: Path | None = None) -> None:
    import json
    with connect(db_path) as conn:
        conn.execute("INSERT INTO paper_sessions (run_at, entry_date, signal_date, decision_json) VALUES (?,?,?,?)",
                     (datetime.now(timezone.utc).isoformat(), decision.get("entry_session"),
                      decision.get("signal_session"), json.dumps(decision)))


def last_decision(db_path: Path | None = None) -> dict | None:
    import json
    with connect(db_path) as conn:
        row = conn.execute("SELECT run_at, decision_json FROM paper_sessions ORDER BY id DESC LIMIT 1").fetchone()
    return {**json.loads(row["decision_json"]), "run_at": row["run_at"]} if row else None


def funded_on(entry_date: str, db_path: Path | None = None) -> int:
    """How many positions the book already holds for one entry session.
    The book opens one a session, so this is the gate that enforces it."""
    with connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE entry_date = ? AND funded = 1",
            (entry_date,)).fetchone()[0])


def has_signal_date(strategy: str, signal_date: str, source: str, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM paper_trades WHERE strategy = ? AND signal_date = ? AND source = ?",
            (strategy, signal_date, source)).fetchone() is not None