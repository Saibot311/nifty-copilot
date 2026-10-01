"""The intraday rules' forward record: each trigger as it happened, at the
option's real price (the strategy pipeline's Phase 3).

The study that judged the three intraday rules had no intraday option
prices and had to model them. From 1 Oct 2026 the five-minute option
snapshots record real ones, and this file records what each rule did on
each session against them: the entry when its bar closed, and the exit,
with the contract's bid, ask and last price from the chain saved in the same
run. A buyer pays the ask and sells at the bid, so both are kept.

Like the forward log, it is evidence only because it is written before the
outcome and never changed after: a row is added once (the same session, rule
and kind a second time is ignored) and the database refuses UPDATE and
DELETE outright.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "intraday_forward.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    trade_day    TEXT NOT NULL,     -- 'YYYY-MM-DD'
    rule         TEXT NOT NULL,     -- noise_band | last_half_hour | opening_range_5m
    kind         TEXT NOT NULL CHECK (kind IN ('entry', 'exit')),
    side         INTEGER NOT NULL,  -- 1 bought the call, -1 the put
    bar_close_at TEXT NOT NULL,     -- when the rule's bar closed, IST
    index_level  REAL NOT NULL,     -- NIFTY at that close
    reason       TEXT,              -- the exit's: back inside | stop | time
    expiry       TEXT,
    strike       REAL,
    option_type  TEXT,
    price_at     TEXT,              -- NSE's time for the chain the prices came from
    bid          REAL,
    ask          REAL,
    ltp          REAL,
    recorded_at  TEXT NOT NULL,     -- when this row was written, IST
    bars_source  TEXT,              -- Kite | Yahoo
    PRIMARY KEY (trade_day, rule, kind)
);
CREATE TRIGGER IF NOT EXISTS events_never_updated BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'the intraday forward record is never edited'); END;
CREATE TRIGGER IF NOT EXISTS events_never_deleted BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'the intraday forward record is never edited'); END;
"""

COLUMNS = ("trade_day", "rule", "kind", "side", "bar_close_at", "index_level", "reason", "expiry", "strike",
           "option_type", "price_at", "bid", "ask", "ltp", "recorded_at", "bars_source")

# An entry or exit priced more than this after its bar closed is kept but not
# counted: the rule trades at the close, not minutes later.
ON_TIME_S = 360


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


def record(event: dict, db_path: Path | None = None) -> bool:
    """Adds the event unless that session's rule already has one of its
    kind; True when it was new."""
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute(f"INSERT OR IGNORE INTO events ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                     tuple(event.get(c) for c in COLUMNS))
        return conn.total_changes > before


def events(trade_day: str | None = None, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        q = "SELECT * FROM events" + (" WHERE trade_day = ?" if trade_day else "") + " ORDER BY trade_day, bar_close_at"
        return [dict(r) for r in conn.execute(q, (trade_day,) if trade_day else ())]


def _late_s(e: dict) -> float | None:
    if not e.get("price_at"):
        return None
    return (datetime.fromisoformat(e["price_at"][:19]) - datetime.fromisoformat(e["bar_close_at"][:19])).total_seconds()


def trades(db_path: Path | None = None) -> list[dict]:
    """Entries paired with their exits. `counted` only when both legs have a
    price and the entry was priced on time; the return is at the ask in and
    the bid out, before brokerage and taxes."""
    rows = events(db_path=db_path)
    exits = {(e["trade_day"], e["rule"]): e for e in rows if e["kind"] == "exit"}
    out = []
    for e in (r for r in rows if r["kind"] == "entry"):
        x = exits.get((e["trade_day"], e["rule"]))
        late, late_out = _late_s(e), _late_s(x) if x else None
        # A price from before the bar closed does not count either: the rule
        # could not have paid it (the record's first entry, before this was
        # checked at the source, was priced 75 seconds early).
        counted = bool(x and e.get("ask") and x.get("bid") is not None and late is not None
                       and 0 <= late <= ON_TIME_S and late_out is not None and 0 <= late_out <= ON_TIME_S)
        out.append({"trade_day": e["trade_day"], "rule": e["rule"], "side": e["side"], "entry_at": e["bar_close_at"],
                    "contract": f"{e['expiry']} {e['strike']:g} {e['option_type']}" if e.get("strike") else None,
                    "ask_in": e.get("ask"), "bid_out": x.get("bid") if x else None,
                    "exit_at": x["bar_close_at"] if x else None, "exit_reason": x.get("reason") if x else None,
                    "entry_late_s": late, "exit_late_s": late_out, "counted": counted,
                    "return_pct": round((x["bid"] / e["ask"] - 1) * 100, 2) if counted else None})
    return out


def summary(db_path: Path | None = None) -> dict:
    """{rule: {trades, mean_pct, first_day}} over counted trades."""
    out: dict = {}
    for t in trades(db_path):
        row = out.setdefault(t["rule"], {"trades": 0, "recorded": 0, "mean_pct": None, "first_day": t["trade_day"],
                                         "_sum": 0.0})
        row["recorded"] += 1
        if t["counted"]:
            row["trades"] += 1
            row["_sum"] += t["return_pct"]
    for row in out.values():
        row["mean_pct"] = round(row["_sum"] / row["trades"], 2) if row["trades"] else None
        del row["_sum"]
    return out
