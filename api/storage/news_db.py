"""The news archive — append-only, and the reason a news edge can ever be
judged at all.

No free source publishes dated Indian market headlines back to 2018. RSS
gives the last day or two and nothing else. So a news study cannot be
backtested; it can only be *started*, the way GIFT Nifty was: snapshot from
today, and a history accumulates.

That is why this file is written every time the feed is read and never
rewritten. A headline is stored once, with the moment this system first saw
it — which is the only timestamp a forward study may use, because it is the
only one that cannot have been assigned after the outcome was known. The
publisher's own `published_at` is kept beside it and is *not* trusted for
research: feeds restamp and backdate.

Like forward_log.db and paper.db, this cannot be regenerated. It is backed
up nightly.
"""

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from .sqlite_open import open_db

DB_PATH = Path(__file__).parent.parent / "data" / "news.db"
IST = timezone(timedelta(hours=5, minutes=30))

OPEN_T = time(9, 15)
CLOSE_T = time(15, 30)

SCHEMA = """
CREATE TABLE IF NOT EXISTS headlines (
    id            TEXT PRIMARY KEY,   -- sha256 of the url, or of the title when there is none
    first_seen    TEXT NOT NULL,      -- when THIS system first saw it (IST). The research clock.
    published_at  TEXT,               -- what the publisher claimed. Kept, not trusted.
    session_date  TEXT NOT NULL,      -- the trading session this belongs to (IST calendar)
    phase         TEXT NOT NULL,      -- pre_open | live | post_close
    source        TEXT NOT NULL,
    source_name   TEXT NOT NULL,
    tier          INTEGER NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT,
    url           TEXT
);
CREATE INDEX IF NOT EXISTS headlines_session ON headlines (session_date, phase);
CREATE INDEX IF NOT EXISTS headlines_seen ON headlines (first_seen);

-- Jev's typed judgments, kept apart from the headline itself so that a
-- re-read of the archive can never be mistaken for a re-judgement, and so a
-- changed question is visibly a new row rather than an edit of an old one.
CREATE TABLE IF NOT EXISTS judgments (
    headline_id   TEXT NOT NULL,
    judged_at     TEXT NOT NULL,
    question_set  TEXT NOT NULL,      -- which registered set of questions was asked
    market_moving REAL,               -- P(this moves the Indian index)
    direction     TEXT,               -- higher | lower | unclear
    dir_conf      REAL,               -- confidence in that direction
    topic         TEXT,
    PRIMARY KEY (headline_id, question_set)
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


def headline_id(item: dict) -> str:
    basis = (item.get("url") or "").strip() or item["title"].strip().lower()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def session_and_phase(seen: datetime) -> tuple[str, str]:
    """Which session a headline belongs to, and where in it.

    The rule an option buyer actually lives under: anything after 15:30 is
    news the next session's open can act on, and is filed against that next
    calendar date as pre_open. Nothing here knows about holidays — the
    research joins on real sessions and drops dates the index did not trade.
    """
    t = seen.timetz().replace(tzinfo=None)
    if t < OPEN_T:
        return seen.date().isoformat(), "pre_open"
    if t <= CLOSE_T:
        return seen.date().isoformat(), "live"
    return (seen.date() + timedelta(days=1)).isoformat(), "pre_open"


def save_many(items: list[dict], now: datetime | None = None, db_path: Path | None = None) -> int:
    """Stores headlines not seen before. Returns how many were new.

    INSERT OR IGNORE, so re-reading a feed every few minutes — which is how
    a live page works — cannot restamp a headline with a later first_seen
    and quietly move it into a session it did not belong to.
    """
    now = now or datetime.now(IST)
    session, phase = session_and_phase(now)
    new = 0
    with connect(db_path) as conn:
        for it in items:
            cur = conn.execute(
                """INSERT OR IGNORE INTO headlines
                   (id, first_seen, published_at, session_date, phase, source, source_name, tier,
                    title, summary, url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (headline_id(it), now.isoformat(timespec="seconds"), it.get("published_at"),
                 session, phase, it["source"], it["source_name"], int(it.get("tier") or 2),
                 it["title"], it.get("summary"), it.get("url")))
            new += cur.rowcount
    return new


def recent(limit: int = 60, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            """SELECT h.*, j.market_moving, j.direction, j.dir_conf, j.topic
               FROM headlines h LEFT JOIN judgments j ON j.headline_id = h.id
               ORDER BY h.first_seen DESC, h.rowid DESC LIMIT ?""", (limit,))]


def for_session(session_date: str, phase: str | None = None, db_path: Path | None = None) -> list[dict]:
    sql = """SELECT h.*, j.market_moving, j.direction, j.dir_conf, j.topic
             FROM headlines h LEFT JOIN judgments j ON j.headline_id = h.id
             WHERE h.session_date = ?"""
    args: list = [session_date]
    if phase:
        sql += " AND h.phase = ?"
        args.append(phase)
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY h.first_seen", args)]


def unjudged(question_set: str, limit: int = 25, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        return [dict(r) for r in conn.execute(
            """SELECT h.* FROM headlines h
               WHERE NOT EXISTS (SELECT 1 FROM judgments j
                                 WHERE j.headline_id = h.id AND j.question_set = ?)
               ORDER BY h.first_seen DESC LIMIT ?""", (question_set, limit))]


def save_judgment(headline_id_: str, question_set: str, verdict: dict,
                  now: datetime | None = None, db_path: Path | None = None) -> None:
    now = now or datetime.now(IST)
    with connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO judgments
               (headline_id, judged_at, question_set, market_moving, direction, dir_conf, topic)
               VALUES (?,?,?,?,?,?,?)""",
            (headline_id_, now.isoformat(timespec="seconds"), question_set,
             verdict.get("market_moving"), verdict.get("direction"),
             verdict.get("dir_conf"), verdict.get("topic")))


def sessions_archived(db_path: Path | None = None) -> int:
    """How many distinct sessions the archive covers — the number that says
    how far the forward study still has to go."""
    path = db_path or DB_PATH
    if not path.exists():
        return 0
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(DISTINCT session_date) FROM headlines").fetchone()[0])


def count(db_path: Path | None = None) -> int:
    path = db_path or DB_PATH
    if not path.exists():
        return 0
    with connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM headlines").fetchone()[0])
