"""The day-ahead forecast: written before its session and never edited,
bands of the stated width, misses explained by fixed checks, and a lean
that only ever looks backwards."""

import math
import sqlite3
from datetime import date, datetime, timedelta

import pytest

import briefing.day_forecast as df
from market_data.kite_session import IST
from options.move_table import UNITS_PER_YEAR


def daily_series(n=300, start=date(2025, 1, 1), seed=1):
    import random
    rnd = random.Random(seed)
    out, d, c = {}, start, 20000.0
    while len(out) < n:
        if d.weekday() < 5:
            o = c * (1 + rnd.gauss(0, 0.002))
            c2 = o * (1 + rnd.gauss(0, 0.008))
            out[d] = {"open": o, "high": max(o, c2) * 1.002, "low": min(o, c2) * 0.998, "close": c2}
            c = c2
        d += timedelta(days=1)
    return out


def test_one_session_after_one_night_is_a_gap_and_a_session_on_the_market_clock():
    s = df.sigma_pct(0.16, date(2026, 9, 29), date(2026, 9, 30))
    assert s == pytest.approx(16 * math.sqrt((0.47 + 1) / UNITS_PER_YEAR))
    assert df.sigma_pct(0.16, date(2026, 10, 1), date(2026, 10, 5)) > s          # over the holiday weekend


def test_the_bands_are_one_and_196_sigma_around_the_last_close():
    daily = daily_series()
    cal = {"k": 1.0, "multipliers": {"event": 1.5, "expiry": 1.0}, "range_ratio": 1.3, "window": 0, "through": None}
    last = max(daily)
    fc = df.make_forecast(last, 20000.0, last + timedelta(days=1), 0.16, cal, [], daily)
    lo, hi = fc["band68"]
    assert math.log(hi / 20000) * 100 == pytest.approx(fc["sigma_pct"], abs=1e-3)
    assert fc["band95"][1] > hi and fc["tag_multiplier"] == 1.0
    ev = df.make_forecast(last, 20000.0, last + timedelta(days=1), 0.16, cal, ["event"], daily)
    assert ev["sigma_pct"] == pytest.approx(fc["sigma_pct"] * 1.5, abs=1e-3)       # event days widened by their record


def test_the_lean_counts_only_sessions_before_the_target():
    daily = daily_series()
    target = sorted(daily)[200]
    before = df.lean(daily, target)
    later = {**daily, **{d: {**b, "close": b["close"] * 3} for d, b in daily.items() if d > target}}
    assert df.lean(later, target) == before


def test_a_miss_names_what_the_forecast_could_not_see():
    fc = {"prev_close": 20000.0, "sigma_pct": 0.8, "band68": [19841.0, 20161.0], "band95": [19688.0, 20318.0],
          "expected_range_pts": 150.0, "lean": {"side": "up"}}
    r = {"open": 20300.0, "high": 20420.0, "low": 20290.0, "close": 20400.0, "ret": math.log(20400 / 20000) * 100,
         "gap": 1.5, "gap_z": 3.0, "tags": ["event"], "iv30": 0.14, "iv30_next": 0.16}
    s = df.score(fc, r)
    assert not s["inside68"] and s["missed"] and s["lean_hit"]
    text = " ".join(s["why"])
    assert "gap" in text and "scheduled event" in text and "rose 14%" in text and "near its high" in text


def test_a_quiet_session_inside_the_band_needs_no_explanation():
    fc = {"prev_close": 20000.0, "sigma_pct": 0.8, "band68": [19841.0, 20161.0], "band95": [19688.0, 20318.0],
          "expected_range_pts": 150.0, "lean": {"side": "down"}}
    r = {"open": 20010.0, "high": 20060.0, "low": 19990.0, "close": 20030.0, "ret": math.log(20030 / 20000) * 100,
         "gap": 0.05, "gap_z": 0.1, "tags": [], "iv30": 0.14, "iv30_next": 0.14}
    s = df.score(fc, r)
    assert s["inside68"] and not s["missed"] and s["why"] == [] and not s["lean_hit"]


def _inputs(daily):
    return {"daily": daily, "iv30": {d: 0.15 for d in daily}, "events": {}, "expiries": set()}


def test_a_forecast_is_written_before_its_session_once_and_scored_after(tmp_path):
    daily = daily_series(80)
    days = sorted(daily)
    last, target = days[-2], days[-1]
    seen = {d: b for d, b in daily.items() if d <= last}
    db = tmp_path / "fc.db"
    evening = datetime.combine(last, datetime.min.time(), tzinfo=IST) + timedelta(hours=21)
    assert df.run_day_forecast(evening, db, _inputs(seen), holidays=set())["forecast"] == target.isoformat()
    assert df.run_day_forecast(evening, db, _inputs(seen), holidays=set())["forecast"] is None     # once
    morning_after = datetime.combine(target, datetime.min.time(), tzinfo=IST) + timedelta(hours=10)
    assert df.run_day_forecast(morning_after, db, _inputs(seen), holidays=set())["forecast"] is None  # never once open
    next_evening = morning_after + timedelta(hours=11)
    w = df.run_day_forecast(next_evening, db, _inputs(daily), holidays=set())
    assert w["scored"] == [target.isoformat()]
    conn = sqlite3.connect(db)
    for sql in ("UPDATE forecasts SET body = '{}'", "DELETE FROM outcomes"):
        with pytest.raises(sqlite3.DatabaseError, match="never edited"):
            conn.execute(sql)
    conn.close()


def test_calibration_is_the_spread_of_recent_errors_and_tags_need_enough_days():
    rows = [{"z": 1.2, "tags": [], "range_ratio": 1.3, "day": date(2026, 1, 1)}] * 130
    cal = df.calibration(rows)
    assert cal["k"] == 1.2 and cal["multipliers"] == {"event": 1.0, "expiry": 1.0} and cal["window"] == 120
    assert df.calibration([{"z": 3.0, "tags": [], "range_ratio": 1, "day": date(2026, 1, 1)}])["k"] == df.K_BOUNDS[1]


# --- never stalling silently (2026-10-06) --------------------------------------------
# On 5 Oct the Kite login had lapsed, the archive stopped at 1 Oct, and the card
# kept showing Monday's forecast into Tuesday with nothing written or scored.

def test_a_close_missing_from_the_kite_archive_comes_from_nses_report():
    daily = daily_series(60)
    last = max(daily)
    nxt = last + timedelta(days=3 if last.weekday() == 4 else 1)
    nse = {last: {"open": 1, "high": 1, "low": 1, "close": 1},          # already archived: Kite's wins
           nxt: {"open": 20100.0, "high": 20200.0, "low": 20000.0, "close": 20150.0}}
    merged, filled = df.fill_from_nse(daily, nse)
    assert filled == [nxt] and merged[nxt]["close"] == 20150.0 and merged[last] == daily[last]


def test_a_close_nse_reported_without_a_range_is_not_used():
    daily = daily_series(60)
    nxt = max(daily) + timedelta(days=7)
    merged, filled = df.fill_from_nse(daily, {nxt: {"open": None, "high": None, "low": None, "close": 20150.0}})
    assert filled == [] and nxt not in merged


def test_missing_implied_volatility_falls_back_to_india_vix_scaled_to_the_series():
    days = [date(2026, 9, d) for d in range(1, 30) if date(2026, 9, d).weekday() < 5]
    iv30 = {d: 0.13 for d in days[:-1]}
    vix = {d: 14.3 for d in days}                                      # VIX runs 10% above the series
    assert df.iv_on(days[-2], iv30, vix) == (0.13, "iv30")
    iv, src = df.iv_on(days[-1], iv30, vix)
    assert iv == pytest.approx(0.13) and "VIX" in src
    assert df.iv_on(days[-1] + timedelta(days=1), iv30, vix) == (None, None)


def test_the_forecast_is_written_from_vix_when_the_iv_series_is_late_and_says_so(tmp_path):
    daily = daily_series(80)
    days = sorted(daily)
    last, target = days[-2], days[-1]
    seen = {d: b for d, b in daily.items() if d <= last}
    inputs = {**_inputs(seen), "iv30": {d: 0.15 for d in days[:-2]}, "vix": {d: 15.0 for d in days}}
    evening = datetime.combine(last, datetime.min.time(), tzinfo=IST) + timedelta(hours=21)
    assert df.run_day_forecast(evening, tmp_path / "fc.db", inputs, holidays=set())["forecast"] == target.isoformat()
    from storage import day_forecast_db as store
    assert "VIX" in store.records(tmp_path / "fc.db")[-1]["forecast"]["iv_source"]


def test_a_missing_forecast_says_so_and_why(tmp_path):
    daily = daily_series(80)
    days = sorted(daily)
    last, target = days[-2], days[-1]
    stale = {d: b for d, b in daily.items() if d < last}               # the last close never arrived
    night = datetime.combine(last, datetime.min.time(), tzinfo=IST) + timedelta(hours=23, minutes=30)
    st = df.forecast_status(night, tmp_path / "fc.db", _inputs(stale), holidays=set())
    assert st["stale"] and st["due"] == target.isoformat()
    assert any(last.isoformat() in r and "close" in r for r in st["reasons"])
    df.run_day_forecast(night, tmp_path / "fc.db", _inputs({d: b for d, b in daily.items() if d <= last}), holidays=set())
    ok = df.forecast_status(night, tmp_path / "fc.db", _inputs({d: b for d, b in daily.items() if d <= last}),
                            holidays=set())
    assert not ok["stale"] and ok["reasons"] == []


def test_before_the_nightly_job_a_missing_forecast_is_only_waiting():
    daily = daily_series(80)
    last = sorted(daily)[-2]
    seen = {d: b for d, b in daily.items() if d <= last}
    evening = datetime.combine(last, datetime.min.time(), tzinfo=IST) + timedelta(hours=17)
    st = df.forecast_status(evening, None, _inputs(seen), holidays=set(), records=[])
    assert not st["stale"] and st["waiting"]


def test_the_record_says_whether_the_width_was_right():
    recs = [{"target_day": f"2026-09-{d:02d}", "outcome": {"z": z, "inside68": abs(z) <= 1, "inside95": abs(z) <= 1.96,
                                                         "lean_hit": True, "move_pts": 10.0}, "forecast": {}}
            for d, z in zip(range(1, 21), [2.0, -2.0] * 10)]
    acc = df.accuracy(recs)
    assert acc["forecasts"] == 20 and acc["inside68_pct"] == 0.0
    assert acc["width_ratio"] == pytest.approx(2.0) and "narrow" in acc["width_reading"]


def test_a_login_catches_up_a_missing_forecast_only_when_it_can_still_count():
    before_open = datetime(2026, 10, 6, 2, 10, tzinfo=IST)
    stale = {"due": "2026-10-06", "stale": True, "waiting": False, "reasons": ["…"]}
    assert df.needs_catch_up(stale, before_open, job_running=False)
    assert not df.needs_catch_up(stale, before_open, job_running=True)                    # the job owns the data then
    assert not df.needs_catch_up(stale, datetime(2026, 10, 6, 9, 20, tzinfo=IST), job_running=False)  # opened
    assert not df.needs_catch_up({**stale, "stale": False, "waiting": True}, before_open, job_running=False)


def test_the_job_counts_as_running_between_its_start_and_done_lines(tmp_path):
    log = tmp_path / "daily_job.log"
    log.write_text("[2026-10-05 19:32:19] daily job start\n[2026-10-05 21:33:27]   news tone series\n")
    assert df.job_running(log)
    log.write_text(log.read_text() + "[2026-10-06 02:41:15] daily job done — FAILED: news tone series\n")
    assert not df.job_running(log)
    assert not df.job_running(tmp_path / "missing.log")


def test_logging_in_to_kite_starts_the_forecast_catch_up(monkeypatch):
    import subprocess

    import main
    started = []
    monkeypatch.setattr(main.kite_session, "check_state", lambda s: True)
    monkeypatch.setattr(main.kite_session, "complete_login", lambda t: {"issued_at": "2026-10-06T02:03:54+05:30"})
    monkeypatch.setattr(main.login_log_db, "record", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append(args))
    main.zerodha_callback(request_token="t", status="success", state="s")
    assert started and started[0][-1].endswith("forecast_catchup.py")
