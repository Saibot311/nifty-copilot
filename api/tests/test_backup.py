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
