"""The forecast learning which way to size its band. What must hold: every
method's width for a day uses only the sessions before it; a challenger
replaces the method in use only when it scores better on the trial window by
the stated margin, in both halves; each night's choice is recorded once and
never edited; and the forecast says which method made it."""

import math
import random
import sqlite3
from datetime import date, datetime, timedelta

import pytest

import briefing.day_forecast as df
import briefing.forecast_learning as fl
from market_data.kite_session import IST


def regime_series(n=700, start=date(2023, 1, 2), seed=3, switching=True):
    """Daily bars whose real volatility switches between quiet and wild every
    40 sessions while implied volatility stays flat: IV says nothing about
    the switch, recent moves do."""
    rnd = random.Random(seed)
    daily, iv30, d, c, i = {}, {}, start, 20000.0, 0
    while len(daily) < n:
        if d.weekday() < 5:
            vol = (0.004 if (i // 40) % 2 == 0 else 0.016) if switching else 0.009
            o = c * (1 + rnd.gauss(0, vol / 4))
            c2 = o * (1 + rnd.gauss(0, vol))
            daily[d] = {"open": o, "high": max(o, c2) * 1.001, "low": min(o, c2) * 0.999, "close": c2}
            iv30[d] = 0.15
            c, i = c2, i + 1
        d += timedelta(days=1)
    return daily, iv30


def _rows(daily, iv30):
    return df.history(daily, iv30, {}, set(), start=min(daily))


def test_each_days_width_uses_only_the_sessions_before_it():
    daily, iv30 = regime_series(400)
    rows = _rows(daily, iv30)
    before = fl.walk_forward(rows)
    later = [dict(r) for r in rows]
    for r in later[300:]:
        r["ret"] *= 5          # rewrite the future
    after = fl.walk_forward(later)
    for m in fl.METHODS:
        assert before[m][:301] == after[m][:301]


def test_recent_moves_win_when_implied_volatility_misses_the_regime():
    daily, iv30 = regime_series()
    d = fl.compare(_rows(daily, iv30), "iv")
    assert d["champion"] != "iv" and d["switched"]
    best = d["champion"]
    assert d["scores"][best] - d["scores"]["iv"] >= fl.MARGIN
    assert all(h[best] - h["iv"] > 0 for h in d["halves"])


def test_a_challenger_that_does_not_clear_the_margin_changes_nothing():
    daily, iv30 = regime_series(switching=False)
    d = fl.compare(_rows(daily, iv30), "iv")
    assert d["champion"] == "iv" and not d["switched"]


def test_the_method_in_use_keeps_its_place_unless_beaten():
    daily, iv30 = regime_series()
    rows = _rows(daily, iv30)
    winner = fl.compare(rows, "iv")["champion"]
    again = fl.compare(rows, winner)
    assert again["champion"] == winner and not again["switched"]


def test_too_short_a_record_keeps_the_method_and_says_why():
    daily, iv30 = regime_series(150)
    d = fl.compare(_rows(daily, iv30), "iv")
    assert d["champion"] == "iv" and not d["switched"] and "sessions" in d["reason"]


def test_a_forecast_says_which_method_made_it_and_the_choice_is_recorded_once(tmp_path):
    daily, iv30 = regime_series()
    days = sorted(daily)
    last = days[-1]
    db = tmp_path / "fc.db"
    evening = datetime.combine(last, datetime.min.time(), tzinfo=IST) + timedelta(hours=21)
    inputs = {"daily": daily, "iv30": iv30, "events": {}, "expiries": set()}
    w = df.run_day_forecast(evening, db, inputs, holidays=set())
    assert w["forecast"]
    from storage import day_forecast_db as store
    fc = store.records(db)[-1]["forecast"]
    choices = store.method_choices(db)
    assert len(choices) == 1 and choices[0]["decided_on"] == last.isoformat()
    assert fc["method"] == choices[0]["choice"]["champion"] != "iv"
    df.run_day_forecast(evening, db, inputs, holidays=set())
    assert len(store.method_choices(db)) == 1                     # once per close
    conn = sqlite3.connect(db)
    for sql in ("UPDATE method_choices SET body = '{}'", "DELETE FROM method_choices"):
        with pytest.raises(sqlite3.DatabaseError, match="never edited"):
            conn.execute(sql)
    conn.close()


def test_the_forecast_width_comes_from_the_method_in_use():
    daily, iv30 = regime_series()
    rows = _rows(daily, iv30)
    last = max(daily)
    target = last + timedelta(days=3 if last.weekday() == 4 else 1)
    for m in fl.METHODS:
        raw = fl.target_raw_sigma(rows, m, iv30[last], last, target)
        cal = df.calibration(fl.method_rows(rows, m))
        fc = df.make_forecast(last, daily[last]["close"], target, iv30[last], cal, [], daily, method=m, raw_pct=raw)
        assert fc["method"] == m
        assert fc["sigma_pct"] == pytest.approx(raw * cal["k"], abs=1e-3)
        assert math.log(fc["band68"][1] / daily[last]["close"]) * 100 == pytest.approx(fc["sigma_pct"], abs=1e-3)
