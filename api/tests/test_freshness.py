"""Every card's data is checked for age against the market clock. What must
hold: a live source is behind when its time lags the session by more than
its limit; a daily source is behind once the nightly job has had its chance
and it still lacks the last close; research is behind when it was computed
before that close; an on-demand study is never called behind; and the
watchdog only fixes data when the nightly job is not running."""

from datetime import date, datetime, timedelta

import pytest

import briefing.freshness as fr
from market_data.kite_session import IST

HOL = {date(2026, 10, 2)}                     # Gandhi Jayanti, a Friday


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


@pytest.mark.parametrize("now,in_session,latest,settled", [
    (at(2026, 10, 6, 12, 53), True, date(2026, 10, 5), date(2026, 10, 5)),
    (at(2026, 10, 5, 17, 0), False, date(2026, 10, 5), date(2026, 10, 1)),   # the job has not run yet
    (at(2026, 10, 5, 23, 30), False, date(2026, 10, 5), date(2026, 10, 5)),
    (at(2026, 10, 6, 2, 0), False, date(2026, 10, 5), date(2026, 10, 5)),
    (at(2026, 10, 4, 11, 0), False, date(2026, 10, 1), date(2026, 10, 1)),   # Sunday, after a Friday holiday
])
def test_the_market_clock(now, in_session, latest, settled):
    c = fr.market_clock(now, HOL)
    assert (c["in_session"], c["latest_closed"], c["settled_close"]) == (in_session, latest, settled)


@pytest.mark.parametrize("raw,expected", [
    ("2026-10-06T12:53:05+05:30", at(2026, 10, 6, 12, 53, ) + timedelta(seconds=5)),
    ("06-Oct-2026 12:53:06", at(2026, 10, 6, 12, 53) + timedelta(seconds=6)),
    ("2026-10-05T20:50:58.552557+00:00", at(2026, 10, 6, 2, 20) + timedelta(seconds=58.552557)),
    ("2026-10-05", at(2026, 10, 5, 15, 30)),                                  # a date is that session's close
    ("2026-10-05T00:00:00", at(2026, 10, 5, 15, 30)),
    ("2026-10-06T09:15", at(2026, 10, 6, 9, 15)),
])
def test_every_time_format_the_endpoints_use(raw, expected):
    assert fr.parse_time(raw) == expected


def test_a_live_source_is_behind_when_it_lags_the_session():
    now = at(2026, 10, 6, 12, 53)
    src = fr.Source("intraday", "Intraday rules", "/api/intraday", "live", ("as_of",), max_age_min=10)
    assert fr.judge(src, {"as_of": "2026-10-06T12:50:00+05:30"}, now, HOL)["status"] == "current"
    late = fr.judge(src, {"as_of": "2026-10-06T12:10:00+05:30"}, now, HOL)
    assert late["status"] == "behind" and "43 min" in late["reason"]


def test_a_live_source_after_the_close_only_needs_the_last_session():
    src = fr.Source("intraday", "Intraday rules", "/api/intraday", "live", ("as_of",), max_age_min=10)
    night = at(2026, 10, 6, 2, 0)
    assert fr.judge(src, {"as_of": "2026-10-05T15:30:00+05:30"}, night, HOL)["status"] == "current"
    assert fr.judge(src, {"as_of": "2026-10-01T15:30:00+05:30"}, night, HOL)["status"] == "behind"


def test_a_daily_source_waits_for_the_nightly_job_then_needs_the_last_close():
    src = fr.Source("iv", "Implied volatility", "/api/iv", "close", ("latest.date",))
    old = {"latest": {"date": "2026-10-01"}}
    assert fr.judge(src, old, at(2026, 10, 5, 17, 0), HOL)["status"] == "current"   # job still to come
    late = fr.judge(src, old, at(2026, 10, 6, 2, 0), HOL)
    assert late["status"] == "behind" and "2026-10-01" in late["reason"] and "2026-10-05" in late["reason"]


def test_research_is_behind_when_computed_before_the_last_close():
    src = fr.Source("structural", "Structural", "/api/structural", "nightly", ("computed_at",))
    assert fr.judge(src, {"computed_at": "2026-10-05T20:51:48+00:00"}, at(2026, 10, 6, 12, 0), HOL)["status"] == "current"
    assert fr.judge(src, {"computed_at": "2026-10-01T20:51:48+00:00"}, at(2026, 10, 6, 12, 0), HOL)["status"] == "behind"


def test_an_on_demand_study_is_never_called_behind():
    src = fr.Source("course", "Course strategies", "/api/course_research", "manual", ("computed_at",))
    r = fr.judge(src, {"computed_at": "2026-09-27T20:48:14"}, at(2026, 10, 6, 12, 0), HOL)
    assert r["status"] == "on demand" and r["as_of"].startswith("2026-09-27")


def test_a_source_that_did_not_answer_or_has_no_time_says_so():
    src = fr.Source("iv", "Implied volatility", "/api/iv", "close", ("latest.date",))
    assert fr.judge(src, None, at(2026, 10, 6, 2, 0), HOL)["status"] == "unavailable"
    assert fr.judge(src, {"latest": {}}, at(2026, 10, 6, 2, 0), HOL)["status"] == "unavailable"


def test_a_source_can_vouch_for_itself():
    src = fr.Source("day_forecast", "The next session", "/api/day_forecast", "self", ("status.stale",))
    ok = fr.judge(src, {"status": {"stale": False, "reasons": []}}, at(2026, 10, 6, 2, 0), HOL)
    bad = fr.judge(src, {"status": {"stale": True, "due": "2026-10-06", "reasons": ["no close"]}}, at(2026, 10, 6, 2, 0), HOL)
    assert ok["status"] == "current" and bad["status"] == "behind" and "no close" in bad["reason"]


def test_the_dashboard_evaluation_covers_every_source_and_counts_what_is_behind():
    payloads = {s.path: None for s in fr.SOURCES}
    out = fr.evaluate(payloads, at(2026, 10, 6, 2, 0), HOL)
    assert len(out["sources"]) == len(fr.SOURCES) and out["unavailable"] == len(fr.SOURCES)
    assert {s["key"] for s in out["sources"]} == {s.key for s in fr.SOURCES}


def test_the_watchdog_fixes_data_only_outside_the_nightly_job_and_not_too_often():
    now = at(2026, 10, 6, 2, 0)
    assert fr.may_fix("options", now, job_running=False, last_tried=None)
    assert not fr.may_fix("options", now, job_running=True, last_tried=None)
    assert not fr.may_fix("options", now, job_running=False, last_tried=now - timedelta(minutes=30))
    assert fr.may_fix("options", now, job_running=False, last_tried=now - timedelta(hours=3))
    assert not fr.may_fix("paper", at(2026, 10, 6, 11, 0), job_running=False, last_tried=None)  # not mid-session


def test_a_service_running_older_code_than_is_on_disk_is_restarted_outside_the_session_only():
    started = at(2026, 10, 3, 0, 57)
    built = at(2026, 10, 6, 2, 13)
    assert fr.service_behind(started, built)
    assert not fr.service_behind(built, started)
    assert fr.restart_now(at(2026, 10, 6, 16, 0), HOL) and not fr.restart_now(at(2026, 10, 6, 11, 0), HOL)


def test_fixes_run_once_each_in_the_order_their_inputs_need():
    ev = {"sources": [
        {"key": "day_forecast", "status": "behind", "fix": ["kite_bars", "options", "iv", "forecast"]},
        {"key": "iv", "status": "behind", "fix": ["options", "iv"]},
        {"key": "paper", "status": "behind", "fix": ["options", "paper"]},
        {"key": "chart", "status": "current", "fix": ["kite_bars"]},
        {"key": "structural", "status": "behind", "fix": ["research"]},
    ]}
    assert fr.plan_fixes(ev) == ["kite_bars", "options", "iv", "research", "forecast", "paper"]


def test_the_api_serves_the_last_check_with_its_age(tmp_path, monkeypatch):
    import json

    import main
    data = tmp_path / "data"
    data.mkdir()
    (data / "freshness.json").write_text(json.dumps({"checked_at": datetime.now(IST).isoformat(timespec="seconds"),
                                                     "sources": [], "behind": 0}))
    monkeypatch.setattr(main, "__file__", str(tmp_path / "main.py"))
    out = main.freshness()
    assert out["behind"] == 0 and out["check_age_min"] is not None and out["check_age_min"] < 1


def test_the_watchdog_starts_the_freshness_check_when_both_services_answer():
    import inspect
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("hw", Path(__file__).parents[1] / "scripts" / "health_watch.py")
    hw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hw)
    src = inspect.getsource(hw.main)
    assert "freshness_check.py" in src and "not unhealthy" in src
