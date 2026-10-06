"""The breakout levels' forward record: each break as it happened, priced from
the option chain saved in the same five-minute run, and — once the session
is over — how it turned out (briefing/breakout_levels.py).

Evidence only because it is written before the outcome and never changed: a
break is added once, its outcome once, and the database refuses UPDATE and
DELETE outright, like the forward log and the intraday record.
"""

import json
import sqlite3
import statistics
from contextlib import contextmanager
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "breakouts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    trade_day    TEXT NOT NULL,
    level        TEXT NOT NULL,     -- pdh | pdl | pdc | orh | orl | pwh | pwl | fch | fcl | oic | oip
    direction    TEXT NOT NULL CHECK (direction IN ('up', 'down')),
    bar_close_at TEXT NOT NULL,     -- when the breaking bar closed, IST
    level_price  REAL NOT NULL,
    index_level  REAL NOT NULL,     -- NIFTY at that close
    expiry       TEXT,
    strike       REAL,
    option_type  TEXT,              -- CE for a break up, PE for a break down
    price_at     TEXT,              -- NSE's time for the chain the prices came from
    bid          REAL,
    ask          REAL,
    ltp          REAL,
    on_time      INTEGER NOT NULL,  -- 1 when priced within six minutes of the bar
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (trade_day, level, direction, bar_close_at)
);
CREATE TABLE IF NOT EXISTS outcomes (
    trade_day    TEXT NOT NULL,
    level        TEXT NOT NULL,
    direction    TEXT NOT NULL,
    bar_close_at TEXT NOT NULL,
    scored_at    TEXT NOT NULL,
    body         TEXT NOT NULL,     -- JSON: points at 15/30/60 min and the close, failed, option % moves
    PRIMARY KEY (trade_day, level, direction, bar_close_at)
);
CREATE TRIGGER IF NOT EXISTS events_never_updated BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'the breakout record is never edited'); END;
CREATE TRIGGER IF NOT EXISTS events_never_deleted BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'the breakout record is never edited'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_never_updated BEFORE UPDATE ON outcomes
BEGIN SELECT RAISE(ABORT, 'the breakout record is never edited'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_never_deleted BEFORE DELETE ON outcomes
BEGIN SELECT RAISE(ABORT, 'the breakout record is never edited'); END;
"""

COLUMNS = ("trade_day", "level", "direction", "bar_close_at", "level_price", "index_level", "expiry", "strike",
           "option_type", "price_at", "bid", "ask", "ltp", "on_time", "recorded_at")
KEY = ("trade_day", "level", "direction", "bar_close_at")


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


def add_event(row: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute(f"INSERT OR IGNORE INTO events ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                     tuple(row.get(c) for c in COLUMNS))
        return conn.total_changes > before


def add_outcome(key: dict, scored_at: str, body: dict, db_path: Path | None = None) -> bool:
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute("INSERT OR IGNORE INTO outcomes VALUES (?, ?, ?, ?, ?, ?)",
                     (*(key[k] for k in KEY), scored_at, json.dumps(body)))
        return conn.total_changes > before


def events(trade_day: str | None = None, db_path: Path | None = None) -> list[dict]:
    """Breaks with their outcome when scored, oldest first; one session's when given."""
    with connect(db_path) as conn:
        sql = ("SELECT e.*, o.body AS outcome FROM events e LEFT JOIN outcomes o USING (trade_day, level, direction, "
               "bar_close_at)")
        rows = conn.execute(sql + (" WHERE e.trade_day = ?" if trade_day else "") + " ORDER BY e.bar_close_at",
                            (trade_day,) if trade_day else ()).fetchall()
    return [{**{k: r[k] for k in r.keys() if k != "outcome"}, "outcome": json.loads(r["outcome"]) if r["outcome"] else None}
            for r in rows]


def summary(db_path: Path | None = None) -> dict:
    """The forward record by level and direction: breaks, how many held 30
    minutes, and the option's median move 30 minutes on, counted only when
    priced on time."""
    out: dict = {}
    for e in events(None, db_path):
        s = out.setdefault(e["level"], {}).setdefault(e["direction"], {"n": 0, "scored": 0, "held_30": 0, "pct_30": []})
        s["n"] += 1
        o = e["outcome"]
        if o:
            s["scored"] += 1
            s["held_30"] += bool(o.get("held_30"))
            if e["on_time"] and o.get("pct_30") is not None:
                s["pct_30"].append(o["pct_30"])
    for lv in out.values():
        for s in lv.values():
            p = s.pop("pct_30")
            s["median_option_pct_30"] = round(statistics.median(p), 1) if p else None
            s["option_counted"] = len(p)
            s["held_30_pct"] = round(s["held_30"] / s["scored"] * 100, 1) if s["scored"] else None
    return out
