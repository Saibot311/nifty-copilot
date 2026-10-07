"""Fixes from the final review: the false alarms a person would meet on a
normal week, and the ways one failure could silence or crash the rest."""

import fcntl
from datetime import date, datetime

from market_data.kite_session import IST
from sentinel import checks_data as d
from sentinel import checks_feeds as f
from sentinel import checks_machine as m
from sentinel import core
from sentinel.core import Check, Finding

PS = """  501 /usr/bin/caffeinate -i -s /x/api/.venv/bin/python /x/api/scripts/daily_job.py
  502 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python /x/api/scripts/daily_job.py
  503 /usr/bin/grep daily_job.py
"""


def test_the_keep_awake_wrapper_is_not_a_second_job():                     # review #1
    assert f.job_pids(PS) == [502]


def test_the_holiday_list_is_judged_by_the_year_it_covers_and_only_in_december():  # #2
    assert f.holidays_known(date(2026, 12, 31), date(2026, 11, 1)).ok
    assert not f.holidays_known(date(2026, 12, 31), date(2026, 12, 5)).ok
    assert f.holidays_known(date(2027, 12, 31), date(2026, 12, 5)).ok
    assert f.year_end(date(2026, 12, 25)) == date(2026, 12, 31)


def test_a_friday_backup_is_fresh_on_monday_morning():                     # #3
    monday = date(2026, 10, 12)
    assert d.backups_fresh({"journal": date(2026, 10, 9)}, monday).ok
    assert d.backups_fresh({"journal": date(2026, 10, 8)}, monday).ok          # one missed night allowed
    assert not d.backups_fresh({"journal": date(2026, 10, 7)}, monday).ok


def test_an_api_that_does_not_answer_is_the_watchdogs_not_slow():           # #4
    r = m.slow_api([float("inf")] * 5)
    assert r.ok and "not answering" in r.summary
    assert not m.slow_api([11.0] * 5).ok
    assert m.slow_render(float("inf")).ok


def test_the_catch_up_runs_only_before_the_open_or_on_a_day_off():          # #5
    state = {}
    assert f.catch_up_allowed(state, datetime(2026, 10, 8, 8, 5, tzinfo=IST), running=False, session_day=True)
    assert not f.catch_up_allowed(state, datetime(2026, 10, 8, 9, 5, tzinfo=IST), running=False, session_day=True)
    assert not f.catch_up_allowed(state, datetime(2026, 10, 8, 16, 0, tzinfo=IST), running=False, session_day=True)
    assert f.catch_up_allowed(state, datetime(2026, 10, 10, 11, 0, tzinfo=IST), running=False, session_day=False)


def test_a_second_nightly_job_exits_at_once(tmp_path):                     # #5
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("dj", Path(__file__).parents[1] / "scripts" / "daily_job.py")
    dj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dj)
    first = dj.acquire_lock(tmp_path / "job.lock")
    assert first is not None and dj.acquire_lock(tmp_path / "job.lock") is None
    first.close()
    assert dj.acquire_lock(tmp_path / "job.lock") is not None


def test_a_job_killed_mid_run_is_not_running():                             # #6
    assert core.job_alive(True, [502]) and not core.job_alive(True, []) and not core.job_alive(False, [502])


def test_the_package_audit_runs_weekly_whatever_the_weekday():              # #7
    assert f.npm_due(None, date(2026, 10, 7)) and f.npm_due("2026-09-30", date(2026, 10, 7))
    assert not f.npm_due("2026-10-02", date(2026, 10, 7))


def test_the_deep_run_inside_the_job_may_repair(monkeypatch, tmp_path):     # #8
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("sr", Path(__file__).parents[1] / "scripts" / "sentinel_run.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    seen = {}
    monkeypatch.setattr(sr, "all_checks", lambda: [])
    monkeypatch.setattr(core, "run", lambda mode, checks, now, **kw: seen.update(kw) or
                        {"checked": 0, "failing": [], "opened": [], "resolved": []})
    monkeypatch.setattr(sr, "OUT", tmp_path / "s.json")
    monkeypatch.setattr(sr, "LOCK", tmp_path / "s.lock")
    sr.main(["--mode", "deep"])
    assert seen.get("job_running") is False


def test_one_check_whose_record_cannot_be_written_does_not_stop_the_rest(tmp_path, monkeypatch):  # #10
    import storage.incidents_db as idb
    sent = []
    real = idb.open_incident
    monkeypatch.setattr(idb, "open_incident", lambda key, *a, **k: (_ for _ in ()).throw(
        RuntimeError("database is locked")) if key == "first" else real(key, *a, **k))
    checks = [Check(k, "data", ("fast",), lambda: Finding(False, "warn", "bad")) for k in ("first", "second")]
    r = core.run("fast", checks, datetime(2026, 10, 7, 5, 0, tzinfo=IST), db_path=tmp_path / "i.db",
                 state_path=tmp_path / "s.json", send=lambda t, b, p="default": sent.append(b) or True,
                 in_session=False, job_running=False)
    assert set(r["failing"]) == {"first", "second"}
    assert any("could not be recorded" in b for b in sent) and len(idb.open_incidents(tmp_path / "i.db")) == 1


def test_overlapping_runs_do_not_both_run(tmp_path):                       # #11
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("sr", Path(__file__).parents[1] / "scripts" / "sentinel_run.py")
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    held = open(tmp_path / "s.lock", "w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sr.LOCK = tmp_path / "s.lock"
    sr.OUT = tmp_path / "sentinel.json"
    sr.all_checks = lambda: []
    assert sr.main(["--mode", "fast"]) == 0                                    # exits quietly, ran nothing
    assert not (tmp_path / "sentinel.json").exists()


def test_a_notification_never_crashes_the_watchdog(monkeypatch):           # #16
    import importlib.util
    from pathlib import Path
    monkeypatch.setattr("sentinel.alerts.send", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network")))
    for name in ("health_watch", "daily_job", "kite_login"):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.notify("test")                                                     # must not raise


def test_nse_is_asked_like_a_browser():                                     # #19
    assert "Mozilla" in f.HOST_HEADERS["User-Agent"]
