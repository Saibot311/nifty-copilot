"""The forward log is the only data here that cannot be regenerated."""

import sqlite3
from datetime import date

from storage.backup import backup_forward_log
from storage.forward_log_db import record_recommendation


def _log(tmp_path, rows=3):
    path = tmp_path / "forward_log.db"
    for i in range(rows):
        record_recommendation({"as_of": f"2026-09-{10 + i}", "action": "NO_TRADE", "regime": "RANGE"},
                              23000.0, db_path=path)
    return path


def test_a_backup_holds_every_row_and_is_verified(tmp_path):
    src = _log(tmp_path)
    r = backup_forward_log(src, tmp_path / "b", today=date(2026, 9, 21))
    assert r["ok"] and r["rows"] == 3
    conn = sqlite3.connect(r["path"])
    assert conn.execute("SELECT COUNT(*) FROM recommendation_log").fetchone()[0] == 3


def test_old_backups_are_rotated_out(tmp_path):
    src = _log(tmp_path)
    for d in range(1, 8):
        backup_forward_log(src, tmp_path / "b", keep=3, today=date(2026, 9, d))
    kept = sorted(p.name for p in (tmp_path / "b").glob("*.db"))
    assert kept == ["forward_log-2026-09-05.db", "forward_log-2026-09-06.db", "forward_log-2026-09-07.db"]


def test_nothing_to_back_up_is_not_an_error(tmp_path):
    assert backup_forward_log(tmp_path / "absent.db", tmp_path / "b")["ok"] is True


# --- found in the 2026-09-24 audit -------------------------------------------

def test_gift_nifty_snapshots_are_backed_up(tmp_path):
    """No free history of GIFT Nifty exists: each nightly snapshot is the only
    copy there will ever be. It was not in the backup set."""
    from storage import backup, gift_nifty_db
    db = tmp_path / "gift.db"
    gift_nifty_db.save({"symbol": "GIFT", "expiry": "2026-10-29", "last": 23100.0, "previous_close": 23000.0,
                        "change_pct": 0.43, "open": 1.0, "high": 1.0, "low": 1.0, "volume": 1.0,
                        "last_trade_time": "x"}, db_path=db)
    r = backup.backup_gift_nifty(source=db, dest_dir=tmp_path / "b", today=date(2026, 9, 24))
    assert r["ok"] and r["rows"] == 1


def test_the_hypothesis_log_is_backed_up_compressed_and_verified(tmp_path):
    """The audit trail behind the multiple-comparisons count. It is appended
    to, never rewritten — and it was in no backup at all."""
    import gzip
    from storage import backup
    log = tmp_path / "hypothesis_log.jsonl"
    log.write_text("".join(f'{{"strategy": "s{i}", "params": {{}}}}' + "\n" for i in range(500)))
    r = backup.backup_hypothesis_log(source=log, dest_dir=tmp_path / "b", today=date(2026, 9, 24))
    assert r["ok"] and r["rows"] == 500
    restored = gzip.decompress((tmp_path / "b" / "hypothesis_log-2026-09-24.jsonl.gz").read_bytes()).decode()
    assert restored == log.read_text()


def test_the_nightly_job_backs_up_again_after_it_has_written():
    """The backup ran first, at 19:30, and the forward log and the paper book
    were written minutes later — so each evening's rows sat in no backup
    until the next weekday. Friday's waited until Monday."""
    import inspect
    import scripts.daily_job as job
    src = inspect.getsource(job.main)
    first = src.index('"forward log, journal and paper backup"')
    again = src.index("backup again")
    assert again > src.index('"paper observation"') and again > first
    step = inspect.getsource(job.step_backup)
    for name in ("backup_forward_log()", "backup_journal()", "backup_paper()", "backup_news()",
                 "backup_gift_nifty()", "backup_hypothesis_log()"):
        assert name in step
