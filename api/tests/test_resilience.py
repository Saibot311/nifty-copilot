"""Staying up. Two processes write these files at once — the API service and
the 19:30 job — and a service can wedge while still running. Neither may take
the dashboard down."""

import sqlite3
import threading

import pytest

from scripts.health_watch import FAILURES_BEFORE_RESTART, should_restart
from storage import journal_db, paper_db
from storage.sqlite_open import BUSY_TIMEOUT_MS, open_db


def test_a_database_is_opened_in_the_mode_that_lets_two_processes_work(tmp_path):
    path = tmp_path / "t.db"
    conn = open_db(path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
    conn.close()


def test_an_unwritable_file_does_not_take_the_process_down(tmp_path):
    # A directory where a file should be: the tuning fails, the caller still
    # gets a connection and finds out on its own terms.
    (tmp_path / "blocked.db").mkdir()
    with pytest.raises(sqlite3.OperationalError):
        open_db(tmp_path / "blocked.db").execute("SELECT 1")


def test_writing_from_two_threads_at_once_does_not_lock_anyone_out(tmp_path, monkeypatch):
    monkeypatch.setattr(journal_db, "DB_PATH", tmp_path / "journal.db")
    errors: list[Exception] = []

    def write(n: int):
        try:
            for i in range(15):
                journal_db.add({"trade_date": "2026-09-23", "decision": "SKIPPED",
                                "reason": f"thread {n} entry {i}"})
        except Exception as e:  # a lock here is the bug this guards
            errors.append(e)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(journal_db.all_entries()) == 60


def test_reading_while_another_thread_writes_never_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_db, "DB_PATH", tmp_path / "paper.db")
    paper_db.add_funds(100_000, "start")
    stop = threading.Event()
    errors: list[Exception] = []

    def writer():
        i = 0
        while not stop.is_set() and i < 40:
            try:
                paper_db.add_funds(1, f"tick {i}")
            except Exception as e:
                errors.append(e)
            i += 1

    def reader():
        for _ in range(40):
            try:
                paper_db.all_trades()
                paper_db.allocated()
            except Exception as e:
                errors.append(e)

    w, r = threading.Thread(target=writer), threading.Thread(target=reader)
    w.start(); r.start(); w.join(); r.join()
    stop.set()
    assert not errors, errors


@pytest.mark.parametrize("fails,restart", [(0, False), (1, False), (2, True), (5, True)])
def test_one_missed_health_check_is_a_cold_start_two_is_a_wedged_service(fails, restart):
    # A rebuilt Next server can take ~15s on its first request; restarting on
    # one miss would fight the deploy it just finished.
    assert should_restart(fails) is restart
    assert FAILURES_BEFORE_RESTART == 2
