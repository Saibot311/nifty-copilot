"""Participant-wise open interest: how each class of trader is positioned in
equity derivatives at every close, from NSE's own daily file.

Four participants — Client (mostly individuals), DII, FII and Pro
(proprietary desks trading their own money). Every option bought is an
option someone sold, so this is the most direct public answer there is to
"who is on the other side of my trade".

Figures are numbers of contracts. Lot sizes have changed over the years
(the contract-size rules of November 2024 among them), so compare shares
and directions across time, not raw counts.
"""

import csv
import io
import sqlite3

from .sqlite_open import open_db
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "participant_oi.db"
PARTICIPANTS = ("Client", "DII", "FII", "Pro")

# NSE's header, normalised: case, stray tabs and trailing spaces vary by year.
COLUMNS = {
    "future index long": "fut_idx_long", "future index short": "fut_idx_short",
    "future stock long": "fut_stk_long", "future stock short": "fut_stk_short",
    "option index call long": "opt_idx_call_long", "option index put long": "opt_idx_put_long",
    "option index call short": "opt_idx_call_short", "option index put short": "opt_idx_put_short",
    "option stock call long": "opt_stk_call_long", "option stock put long": "opt_stk_put_long",
    "option stock call short": "opt_stk_call_short", "option stock put short": "opt_stk_put_short",
    "total long contracts": "total_long", "total short contracts": "total_short",
}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS participant_oi (
    trade_date  TEXT NOT NULL,
    participant TEXT NOT NULL,
    {", ".join(f"{c} REAL" for c in COLUMNS.values())},
    PRIMARY KEY (trade_date, participant)
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def parse(text: str) -> list[dict]:
    """NSE's CSV: a title line, a header, one row per participant, a TOTAL."""
    rows = list(csv.reader(io.StringIO(text)))
    header_at = next((i for i, r in enumerate(rows) if r and r[0].strip().lower() == "client type"), None)
    if header_at is None:
        return []
    names = [COLUMNS.get(" ".join(h.split()).lower()) for h in rows[header_at][1:]]
    out = []
    for r in rows[header_at + 1:]:
        if not r or r[0].strip() not in PARTICIPANTS:
            continue
        rec = {"participant": r[0].strip()}
        for name, v in zip(names, r[1:]):
            if name:
                rec[name] = float(v.replace(",", "").strip() or 0)
        out.append(rec)
    return out


def save_day(trade_date: str, rows: list[dict], db_path: Path | None = None) -> int:
    with connect(db_path) as conn:
        for r in rows:
            cols = ["trade_date", "participant", *[c for c in COLUMNS.values() if c in r]]
            conn.execute(f"INSERT OR REPLACE INTO participant_oi ({', '.join(cols)}) VALUES "
                         f"({', '.join('?' * len(cols))})", [trade_date, *[r[c] for c in cols[1:]]])
    return len(rows)


def days_saved(db_path: Path | None = None) -> set[str]:
    with connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM participant_oi")}


def load(db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM participant_oi ORDER BY trade_date, participant")]