"""The sentinel's engine. What must hold: a failing check opens one incident
and sends one message, however many runs see it; a check that raises is a
finding and the others still run; an incident resolves only after two
passes in a row; repairs are rate-limited and refused during the nightly job
and the session unless allowed, with the reason on the record."""

from datetime import datetime, timedelta

import pytest

import storage.incidents_db as idb
from market_data.kite_session import IST
from sentinel import core
from sentinel.core import Check, Finding

T0 = datetime(2026, 10, 7, 5, 0, tzinfo=IST)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "REPAIRS", {})
    sent = []
    kw = dict(db_path=tmp_path / "i.db", state_path=tmp_path / "s.json",
              send=lambda title, body, priority="default": sent.append((title, body)) or True,
              in_session=False, job_running=False)
    return kw, sent


def _check(result, key="disk", repair=None, raises=False):
    def detect():
        if raises:
            raise RuntimeError("boom")
        return result()
    return Check(key, "data", ("fast",), detect, repair)


def test_a_failing_check_opens_one_incident_and_one_alert(env):
    kw, sent = env
    c = _check(lambda: Finding(False, "warn", "4 GB free"))
    core.run("fast", [c], T0, **kw)
    core.run("fast", [c], T0 + timedelta(minutes=10), **kw)
    (o,) = idb.open_incidents(kw["db_path"])
    assert o["seen_count"] == 2 and len(sent) == 1 and "4 GB free" in sent[0][1]


def test_a_check_that_raises_is_a_finding_and_the_rest_still_run(env):
    kw, _ = env
    r = core.run("fast", [_check(None, "broken", raises=True), _check(lambda: Finding(False, "warn", "x"), "disk")], T0, **kw)
    assert set(r["failing"]) == {"broken", "disk"}
    assert "check broken: boom" in [o["summary"] for o in idb.open_incidents(kw["db_path"])][0]


def test_it_resolves_only_after_two_passes(env):
    kw, sent = env
    seq = iter([False, True, False, True, True])
    c = _check(lambda: Finding(next(seq), "warn", "flaky"))
    for k in range(5):
        r = core.run("fast", [c], T0 + timedelta(minutes=10 * k), **kw)
    assert r["resolved"] == ["disk"] and idb.open_incidents(kw["db_path"]) == []
    assert len(idb.recent(14, kw["db_path"], now=T0.isoformat())) == 1           # one incident, not two
    assert [t for t, _ in sent if t.startswith("Resolved")] and len(sent) == 2


def test_repairs_are_rate_limited_and_refused_during_the_job_and_session(env):
    kw, _ = env
    calls = []
    core.register_repair("tidy", lambda: calls.append(1) or (True, "freed 1 GB"))
    c = _check(lambda: Finding(False, "warn", "low"), repair="tidy")
    core.run("fast", [c], T0, **{**kw, "job_running": True})
    core.run("fast", [c], T0 + timedelta(minutes=10), **{**kw, "in_session": True})
    core.run("fast", [c], T0 + timedelta(minutes=20), **kw)
    core.run("fast", [c], T0 + timedelta(minutes=30), **kw)
    assert calls == [1]
    details = [r["detail"] for r in idb.open_incidents(kw["db_path"])[0]["repairs"]]
    assert "nightly job" in details[0] and "market hours" in details[1] and "freed 1 GB" in details[2]
    assert "tried" in details[3]


def test_a_repair_allowed_in_session_runs_in_session(env):
    kw, _ = env
    core.register_repair("restart_api", lambda: (True, "restarted"), allow_in_session=True)
    core.run("fast", [_check(lambda: Finding(False, "critical", "API hung"), "slow_api", "restart_api")], T0,
             **{**kw, "in_session": True})
    assert "restarted" in idb.open_incidents(kw["db_path"])[0]["repairs"][0]["detail"]


def test_checks_of_another_mode_do_not_run(env):
    kw, _ = env
    deep = Check("integrity", "data", ("deep",), lambda: Finding(False, "critical", "corrupt"))
    assert core.run("fast", [deep], T0, **kw)["checked"] == 0
