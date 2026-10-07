"""Feed, job, time and security checks at the spec's thresholds."""

from datetime import date, datetime

from market_data.kite_session import IST
from sentinel import checks_feeds as f

CHAIN = {"records": {"underlyingValue": 22776.1, "expiryDates": ["13-Oct-2026"], "data": [
    {"strikePrice": 22800, "CE": {"lastPrice": 1, "openInterest": 2, "impliedVolatility": 3, "buyPrice1": 4,
                                  "sellPrice1": 5}, "PE": {"lastPrice": 1, "openInterest": 2, "impliedVolatility": 3,
                                                          "buyPrice1": 4, "sellPrice1": 5}}]}}


def test_three_failed_snapshot_runs_in_session():
    ok = ["10:00 276 new of 276", "10:05 276 new of 276", "10:10 276 new of 276"]
    bad = ["10:00 FAILED — 403", "10:05 FAILED — 403", "10:10 FAILED — 403"]
    assert f.snapshots_failing(ok, True).ok and not f.snapshots_failing(bad, True).ok
    assert f.snapshots_failing(bad, False).ok                      # outside the session nothing runs


def test_a_changed_chain_names_the_missing_field():
    assert f.chain_shape(CHAIN).ok
    import copy
    c = copy.deepcopy(CHAIN)
    del c["records"]["data"][0]["CE"]["impliedVolatility"]
    r = f.chain_shape(c)
    assert not r.ok and r.severity == "critical" and "impliedVolatility" in r.summary
    assert not f.chain_shape({"records": {}}).ok
    assert f.quote_shape({"last": 1, "open": 1, "high": 1, "low": 1, "market_time": "x"}).ok
    assert "market_time" in f.quote_shape({"last": 1, "open": 1, "high": 1, "low": 1}).summary


def test_a_host_down_two_nights_running():
    r, hist = f.hosts_down({"yahoo": False, "gdelt": True}, {"yahoo": 1})
    assert not r.ok and "yahoo" in r.summary and hist == {"yahoo": 2, "gdelt": 0}
    r, hist = f.hosts_down({"yahoo": False}, {})
    assert r.ok and hist == {"yahoo": 1}


LOG = """[2026-10-06 19:30:01] daily job start
[2026-10-07 03:36:01] daily job done
"""


def test_a_missed_nightly_job_is_found_after_eight():
    morning = datetime(2026, 10, 8, 8, 5, tzinfo=IST)
    assert f.job_missed(LOG, date(2026, 10, 6), morning).ok        # the 6 Oct run finished
    assert not f.job_missed(LOG, date(2026, 10, 7), morning).ok    # no run after 7 Oct's session
    assert f.job_missed(LOG, date(2026, 10, 7), morning.replace(hour=7, minute=59)).ok


def test_an_overrunning_job_names_its_step():
    started = datetime(2026, 10, 7, 19, 30, tzinfo=IST)
    assert f.job_overrun(started, datetime(2026, 10, 7, 23, 0, tzinfo=IST), "x").ok
    r = f.job_overrun(started, datetime(2026, 10, 7, 23, 31, tzinfo=IST), "replication on other indices")
    assert not r.ok and "replication" in r.summary
    assert f.job_overrun(None, datetime(2026, 10, 7, 23, 31, tzinfo=IST), "").ok


def test_two_jobs_at_once():
    assert f.job_twice([101]).ok and not f.job_twice([101, 202]).ok


def test_the_catch_up_runs_once_a_day_and_never_twice():
    assert f.catch_up_allowed({}, date(2026, 10, 8), running=False)
    assert not f.catch_up_allowed({"catch_up_on": "2026-10-08"}, date(2026, 10, 8), running=False)
    assert not f.catch_up_allowed({}, date(2026, 10, 8), running=True)


def test_time_checks():
    assert f.holidays_known(date(2026, 12, 25), date(2026, 10, 7)).ok
    assert not f.holidays_known(date(2026, 12, 25), date(2026, 11, 1)).ok
    assert f.lot_size(65, 65).ok and f.lot_size(75, 65).severity == "critical" and not f.lot_size(75, 65).ok
    assert f.rate_card_age("2026-09-27", date(2027, 3, 1)).ok and not f.rate_card_age("2026-09-27", date(2027, 4, 1)).ok


def test_security_from_the_audit_and_npm():
    rows = [{"id": "1.1", "status": "PASS"}, {"id": "15.1", "status": "FAIL", "title": "reachable"}]
    assert not f.audit_security(rows).ok and f.audit_security(rows[:1]).ok
    assert f.npm_audit({"metadata": {"vulnerabilities": {"high": 0, "critical": 0, "moderate": 3}}}).ok
    assert not f.npm_audit({"metadata": {"vulnerabilities": {"high": 1, "critical": 0}}}).ok
