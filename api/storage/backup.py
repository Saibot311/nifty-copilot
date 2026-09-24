"""Backups of the files in this project that cannot be regenerated: the
forward log, the journal, the paper book, the news archive, the GIFT Nifty
snapshots and the hypothesis log. (It began with the forward log alone.) Every other data file can be rebuilt from an exchange archive
or a broker; each forward-log row was written before its outcome existed,
and a row recreated afterwards would be a backtest in disguise.

Until the audit it had no backup at all.

Uses SQLite's online backup API, not a file copy: a copy taken while the
API is writing can be torn, and a backup that restores to a corrupt file is
worse than none because it is trusted. Each backup is re-opened and its row
count checked against the source before it counts.

Goes to api/data/backups/ by default — which protects against a bad write
or an accidental delete, but not against losing the disk. Set BACKUP_DIR in
api/.env to a synced folder (iCloud Drive, Dropbox) for that.
"""

import sqlite3
from datetime import date
from pathlib import Path

from market_data.kite_session import _env

from .forward_log_db import DB_PATH

DEFAULT_DIR = Path(__file__).parent.parent / "data" / "backups"
KEEP = 30


def backup_forward_log(source: Path | None = None, dest_dir: Path | None = None, keep: int = KEEP,
                       today: date | None = None) -> dict:
    return _backup(source or DB_PATH, "forward_log", "recommendation_log", dest_dir, keep, today)


def backup_journal(source: Path | None = None, dest_dir: Path | None = None, keep: int = KEEP,
                   today: date | None = None) -> dict:
    """The trade journal is the user's own record and, like the forward log,
    cannot be rebuilt from anything else."""
    from .journal_db import DB_PATH as JOURNAL_PATH
    return _backup(source or JOURNAL_PATH, "journal", "journal", dest_dir, keep, today)


def backup_paper(source: Path | None = None, dest_dir: Path | None = None, keep: int = KEEP,
                 today: date | None = None) -> dict:
    """Paper observation is forward evidence: it cannot be recreated either."""
    from .paper_db import DB_PATH as PAPER_PATH
    return _backup(source or PAPER_PATH, "paper", "paper_trades", dest_dir, keep, today)


def backup_news(source: Path | None = None, dest_dir: Path | None = None, keep: int = KEEP,
                today: date | None = None) -> dict:
    """The headline archive is forward-only and cannot be rebuilt.

    No free source publishes dated Indian market headlines going back, so
    every row here exists only because this system was running that day and
    wrote down when it first saw the story. Lose the file and those days are
    gone. (news_tone.db is NOT in this set: it is a cache of a public GDELT
    series and can simply be fetched again.)
    """
    from .news_db import DB_PATH as NEWS_PATH
    return _backup(source or NEWS_PATH, "news", "headlines", dest_dir, keep, today)


def backup_gift_nifty(source: Path | None = None, dest_dir: Path | None = None, keep: int = KEEP,
                      today: date | None = None) -> dict:
    """NSE IX publishes no free history, so each nightly GIFT Nifty snapshot
    is the only copy that will ever exist."""
    from .gift_nifty_db import DB_PATH as GIFT_PATH
    return _backup(source or GIFT_PATH, "gift_nifty", "snapshots", dest_dir, keep, today)


def backup_hypothesis_log(source: Path | None = None, dest_dir: Path | None = None, keep: int = KEEP,
                          today: date | None = None) -> dict:
    """The audit trail of every strategy and parameter set ever run — the
    record the multiple-comparisons count is read from. It is plain JSON
    lines, not SQLite, so it is read under the same file lock the writers
    take (never a half-written line), gzipped, and checked by decompressing
    the copy and comparing it with what was read."""
    import fcntl
    import gzip
    import hashlib

    if source is None:
        from backtest.hypothesis_log import LOG_PATH as source
    if not source.exists():
        return {"ok": True, "path": None, "rows": 0, "summary": "no hypothesis log yet — nothing to back up"}
    dest_dir = dest_dir or Path(_env("BACKUP_DIR") or DEFAULT_DIR).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"hypothesis_log-{(today or date.today()).isoformat()}.jsonl.gz"
    with open(source, "rb") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            data = f.read()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    dest.write_bytes(gzip.compress(data))
    back = gzip.decompress(dest.read_bytes())
    rows = data.count(b"\n")
    if hashlib.sha256(back).digest() != hashlib.sha256(data).digest():
        dest.unlink(missing_ok=True)
        return {"ok": False, "path": None, "rows": 0, "summary": "BACKUP FAILED verification: hypothesis log copy differs"}
    old = sorted(dest_dir.glob("hypothesis_log-*.jsonl.gz"))[:-keep] if keep else []
    for f in old:
        f.unlink()
    return {"ok": True, "path": str(dest), "rows": rows,
            "summary": f"{rows} rows backed up and verified -> {dest}"
                       + (f"; removed {len(old)} older backup(s)" if old else "")}


def _backup(source: Path, stem: str, table: str, dest_dir: Path | None, keep: int, today: date | None) -> dict:
    if not source.exists():
        return {"ok": True, "path": None, "rows": 0, "summary": f"no {stem.replace('_', ' ')} yet — nothing to back up"}
    dest_dir = dest_dir or Path(_env("BACKUP_DIR") or DEFAULT_DIR).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stem}-{(today or date.today()).isoformat()}.db"

    src = sqlite3.connect(source)
    try:
        want = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()

    check = sqlite3.connect(dest)
    try:
        got = check.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        intact = check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        check.close()
    if got != want or not intact:
        dest.unlink(missing_ok=True)
        return {"ok": False, "path": None, "rows": got,
                "summary": f"BACKUP FAILED verification: {got} of {want} rows, integrity {'ok' if intact else 'bad'}"}

    old = sorted(dest_dir.glob(f"{stem}-*.db"))[:-keep] if keep else []
    for f in old:
        f.unlink()
    return {"ok": True, "path": str(dest), "rows": got,
            "summary": f"{got} rows backed up and verified -> {dest}"
                       + (f"; removed {len(old)} older backup(s)" if old else "")}
