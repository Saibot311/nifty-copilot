"""Kronos beside the app's forecast: bands read straight from its sampled
paths, each forecast written before its outcome and never edited, the live
one only inside the session, and nothing run when the model is absent."""

import sqlite3
from datetime import datetime

import pandas as pd
import pytest

import briefing.kronos_forecast as kf
from market_data.kite_session import IST
from storage import kronos_db as db


def fake_run(level):
    def run(candles, jobs, lookback, paths=kf.PATHS, timeout=0):
        return {"model": "test", "seconds": 0.1,
                "results": {j["id"]: {"closes": [[level + k - 20] * len(j["future"]) for k in range(41)],
                                      "highs": [], "lows": []} for j in jobs}}
    return run


def test_bands_are_the_percentiles_of_the_sampled_paths():
    s = kf.summarise({"closes": [[100.0 + k] for k in range(101)]}, 120.0)
    assert s["median"] == 150 and s["band68"] == [116, 184] and s["band95"] == [102.5, 197.5]
    assert s["direction"] == "up" and s["median_move"] == 30


def test_a_score_is_against_the_last_close_and_the_bands():
    fc = {"last_close": 100.0, "median": 103.0, "band68": [98.0, 106.0], "band95": [95.0, 110.0], "direction": "up"}
    assert kf.score(fc, 107.0) == {"close": 107.0, "move": 7.0, "inside68": False, "inside95": True,
                                   "direction_hit": True, "error": 4.0}


def test_the_next_hour_stays_inside_the_session():
    last = datetime(2026, 10, 12, 14, 50, tzinfo=IST)
    slots = kf.next_slots(last)
    assert [s.strftime("%H:%M") for s in slots] == ["14:55", "15:00", "15:05", "15:10", "15:15", "15:20", "15:25"]
    assert len(kf.next_slots(datetime(2026, 10, 12, 10, 0, tzinfo=IST))) == 12


def test_daily_is_written_before_the_session_once_and_scored_after(tmp_path, monkeypatch):
    path = tmp_path / "k.db"
    candles = [{"t": f"2026-10-0{d}T15:30:00+05:30", "open": 1, "high": 1, "low": 1, "close": 22500.0 + d, "volume": 0}
               for d in (5, 6, 7, 8, 9)]
    monkeypatch.setattr(kf, "_daily_candles", lambda upto: list(candles))
    monkeypatch.setattr(kf, "available", lambda: True)
    monkeypatch.setattr(kf, "run", fake_run(22500.0))
    sat = datetime(2026, 10, 10, 12, 0, tzinfo=IST)
    assert kf.run_daily(sat, path, holidays=set())["forecast"] == "2026-10-12"
    assert kf.run_daily(sat, path, holidays=set())["forecast"] is None               # once
    candles.append({"t": "2026-10-12T15:30:00+05:30", "open": 1, "high": 1, "low": 1, "close": 22400.0, "volume": 0})
    mon_evening = datetime(2026, 10, 12, 20, 0, tzinfo=IST)
    w = kf.run_daily(mon_evening, path, holidays=set())
    assert w["scored"] == ["2026-10-12"]
    out = db.records("daily", path)[0]["outcome"]
    assert out["close"] == 22400.0 and out["move"] == round(22400.0 - 22509.0, 1)
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match="never edited"):
        conn.execute("UPDATE forecasts SET body = '{}'")
    conn.close()


def _bars(day, upto):
    idx = pd.date_range(f"{day} 09:15", f"{day} {upto}", freq="5min", tz=IST)
    return pd.DataFrame({"open": 22500.0, "high": 22510.0, "low": 22490.0, "close": 22500.0}, index=idx)


def test_live_forecasts_the_next_hour_in_session_and_scores_it_when_it_has_passed(tmp_path, monkeypatch):
    path = tmp_path / "k.db"
    monkeypatch.setattr(kf, "available", lambda: True)
    monkeypatch.setattr(kf, "run", fake_run(22520.0))
    w = kf.run_live(datetime(2026, 10, 12, 10, 1, tzinfo=IST), path, bars=_bars("2026-10-12", "09:55"))
    assert w["forecast"] == "2026-10-12T11:00:00+05:30"
    later = _bars("2026-10-12", "11:00")
    later.loc[pd.Timestamp("2026-10-12 10:55", tz=IST), "close"] = 22530.0
    w = kf.run_live(datetime(2026, 10, 12, 11, 1, tzinfo=IST), path, bars=later)
    assert w["scored"] == ["2026-10-12T11:00:00+05:30"]
    assert db.records("live", path)[0]["outcome"]["close"] == 22530.0


def test_no_live_forecast_outside_the_session_or_without_the_model(tmp_path, monkeypatch):
    path = tmp_path / "k.db"
    monkeypatch.setattr(kf, "run", fake_run(22520.0))
    monkeypatch.setattr(kf, "available", lambda: True)
    assert kf.run_live(datetime(2026, 10, 10, 11, 0, tzinfo=IST), path, bars=_bars("2026-10-09", "15:25"))["forecast"] is None
    monkeypatch.setattr(kf, "available", lambda: False)
    assert kf.run_live(datetime(2026, 10, 12, 10, 1, tzinfo=IST), path, bars=_bars("2026-10-12", "09:55"))["forecast"] is None
