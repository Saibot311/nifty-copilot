"""Data and backup checks: a corrupt database is named (and never touched),
an oversized WAL is checkpointed outside the session, missing sessions are
listed, a stale backup is found, and a backup is proved by opening it."""

import sqlite3
from datetime import date

from sentinel import checks_data as d


def _db(path, rows=3, table="t"):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table} (x)")
    conn.executemany(f"INSERT INTO {table} VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def test_a_corrupt_copy_is_named(tmp_path):
    good = _db(tmp_path / "good.db")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    f = d.integrity([good, bad])
    assert not f.ok and f.severity == "critical" and "bad.db" in f.summary and "good.db" not in f.summary
    assert d.integrity([good]).ok


def test_a_large_wal_is_found_and_checkpointed(tmp_path):
    db = _db(tmp_path / "big.db")
    (tmp_path / "big.db-wal").write_bytes(b"\0" * 2048)
    assert not d.wal_sizes([db], limit_bytes=1024).ok and d.wal_sizes([db], limit_bytes=4096).ok
    ok, msg = d.checkpoint_wal([db])
    assert ok and "big.db" in msg


def test_missing_sessions_are_listed():
    sessions = [date(2026, 10, 1), date(2026, 10, 5), date(2026, 10, 6)]
    f = d.gaps({"1d": {"2026-10-01", "2026-10-06"}, "5m": {"2026-10-01", "2026-10-05", "2026-10-06"}}, sessions)
    assert not f.ok and "2026-10-05" in f.summary and f.evidence["missing"] == {"1d": ["2026-10-05"]}
    assert d.gaps({"1d": {"2026-10-01"}}, [date(2026, 10, 1)]).ok


def test_a_stale_backup_is_found():
    today = date(2026, 10, 7)
    assert d.backups_fresh({"journal": date(2026, 10, 6), "paper": date(2026, 10, 5)}, today).ok
    f = d.backups_fresh({"journal": date(2026, 10, 4), "paper": None}, today)
    assert not f.ok and "journal" in f.summary and "paper" in f.summary


def test_the_restore_test_opens_the_backup_and_counts_rows(tmp_path):
    live = _db(tmp_path / "live.db", rows=5)
    assert d.restore_test(_db(tmp_path / "b1.db", rows=4), live, "t").ok          # a backup may trail live
    assert not d.restore_test(_db(tmp_path / "b2.db", rows=6), live, "t").ok      # never lead it
    bad = tmp_path / "b3.db"
    bad.write_bytes(b"not a database")
    assert not d.restore_test(bad, live, "t").ok
    assert bad.read_bytes() == b"not a database"                                   # never modified


def test_every_irreplaceable_database_is_listed_once():
    stems = [s for s, _, _ in d.IRREPLACEABLE]
    assert len(stems) == len(set(stems))
    assert {"forward_log", "journal", "paper", "breakouts", "incidents", "day_forecast"} <= set(stems)
