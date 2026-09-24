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


def test_the_research_comparison_is_not_recomputed_on_every_page_load(monkeypatch):
    """It ran all 26 backtests — ten seconds — inside every render of the
    dashboard, and every render waited for it and appended 26 rows to the
    hypothesis log. Its inputs change once a day."""
    import cache
    import main
    calls = []
    monkeypatch.setattr(main, "run_all_strategies", lambda **kw: calls.append(kw) or {"results": {}})
    cache.invalidate()
    main.research_compare(symbol="^NSEI", days=7000, hold_days=10)
    main.research_compare(symbol="^NSEI", days=7000, hold_days=10)
    assert len(calls) == 1
    cache.invalidate()


def test_the_watchdogs_launchd_log_is_not_the_file_the_script_writes():
    """launchd could not open health_watch.log — the script had created it,
    from a shell, without the permission tag launchd needs — so every run
    failed before Python started (exit 78) and the watchdog never ran once."""
    from pathlib import Path
    installer = (Path(__file__).resolve().parents[2] / "scripts" / "install_app_services.sh").read_text()
    block = installer[installer.index('cat > "$HOME/Library/LaunchAgents/$WATCH_LABEL.plist"'):]
    block = block[: block.index("\nPLIST\n")]
    assert "health_watch.launchd.log" in block and "data/health_watch.log<" not in block


def test_the_services_may_hold_more_than_256_files():
    from pathlib import Path
    installer = (Path(__file__).resolve().parents[2] / "scripts" / "install_app_services.sh").read_text()
    assert "SoftResourceLimits" in installer and "NumberOfFiles" in installer


def test_the_deep_health_check_fails_when_no_file_can_be_opened(monkeypatch):
    """/health opens nothing, so it answers even when the API has run out of
    file descriptors and every real endpoint is failing. The watchdog asks
    the deep one."""
    import tempfile

    import pytest
    from fastapi import HTTPException

    import main
    assert main.health_deep()["status"] == "ok"

    def out_of_files(*a, **k):
        raise OSError(24, "Too many open files")
    monkeypatch.setattr(tempfile, "TemporaryFile", out_of_files)
    with pytest.raises(HTTPException) as e:
        main.health_deep()
    assert e.value.status_code == 503


def test_the_watchdog_asks_the_deep_check():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("hw", Path(__file__).resolve().parents[1] / "scripts" / "health_watch.py")
    hw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hw)
    assert hw.SERVICES["com.niftycopilot.api"].endswith("/health/deep")
