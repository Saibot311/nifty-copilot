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
