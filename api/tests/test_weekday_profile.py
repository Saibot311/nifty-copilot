"""The weekday card: swings measured the stated way, today's path never
compared with itself, and "similar days" shown as a spread, not a call."""

from datetime import date

import pandas as pd

import briefing.weekday_profile as wp

SLOTS = pd.timedelta_range("09:15:00", "15:25:00", freq="5min")


def day_bars(d: str, path: dict, base=20000.0) -> pd.DataFrame:
    """Flat bars at `base`, with {"HH:MM": (open, high, low, close)} overrides."""
    idx = pd.DatetimeIndex([pd.Timestamp(d) + t for t in SLOTS]).tz_localize("Asia/Kolkata")
    df = pd.DataFrame({"open": base, "high": base, "low": base, "close": base}, index=idx)
    for clock, ohlc in path.items():
        df.loc[pd.Timestamp(f"{d} {clock}").tz_localize("Asia/Kolkata"), ["open", "high", "low", "close"]] = ohlc
    return df


def test_a_swing_ends_only_on_a_reversal_of_the_stated_size():
    # up 200 from 20,000 (1%), back 76 (0.38% of 20,200: a reversal), then up 30 (0.15%: not one)
    times = ["09:20", "09:40", "10:30", "11:00"]
    highs = [20100, 20200, 20124, 20154]
    lows = [20000, 20150, 20124, 20124]
    sw = wp.swings(times, highs, lows, 20000.0)
    assert [(s["dir"], round(s["points"]), s["ends"], s["done"]) for s in sw] == \
        [(1, 200, "09:40", True), (-1, 76, "10:30", False)]


def test_a_quiet_day_has_no_swing():
    assert wp.swings(["09:15", "09:20"], [20020, 20030], [19990, 19985], 20000.0) == []


def test_the_hourly_path_reads_the_bar_that_ends_at_each_hour():
    g = day_bars("2026-09-24", {"10:10": (20000, 20060, 20000, 20050), "15:25": (20000, 20000, 19900, 19940)})
    s = wp.session(g, 19980.0, False)
    assert s["path"]["10:15"] == 50 and s["path"]["15:30"] == -60 and s["complete"]
    assert round(s["gap_pct"], 3) == round((20000 / 19980 - 1) * 100, 3)


def _row(d, up_first, first, back, close, path=None):
    sw = [{"dir": 1 if up_first else -1, "points": first, "ends": "09:40", "done": True},
          {"dir": -1 if up_first else 1, "points": back, "ends": "11:00", "done": True}]
    return {"date": d, "weekday": wp.WEEKDAYS[d.weekday()], "expiry": False, "open": 20000.0, "up": first,
            "down": back, "now": close, "gap_pct": 0.1, "path": path or {}, "swings": sw, "complete": True}


def test_the_profile_is_medians_in_points_and_the_share_that_went_up_first():
    rows = [_row(date(2026, 9, d), True, 100, 80, 20) for d in (1, 8)] + [_row(date(2026, 9, 15), False, 150, 60, -40)]
    p = wp.profile(rows)
    assert p["sessions"] == 3 and p["up_first_pct"] == 67 and p["first_up"] == 100 and p["back_after_up"] == 80
    assert p["first_down"] == 150 and p["first_swing_ends"] == "09:45" and p["open_to_close"] == 20


def test_similar_days_match_on_the_hours_reached_and_report_both_outcomes():
    today = {"open": 22000.0, "path": {"10:15": -110.0, "11:15": -220.0}, "now": -230.0}
    near_up = _row(date(2026, 1, 1), False, 100, 50, 60, {"10:15": -95.0, "11:15": -205.0, "15:30": 60.0})
    near_dn = _row(date(2026, 2, 5), False, 100, 50, -300, {"10:15": -100.0, "11:15": -190.0, "15:30": -300.0})
    far = _row(date(2026, 3, 5), True, 100, 50, 10, {"10:15": 150.0, "11:15": 160.0, "15:30": 10.0})
    out = wp.similar(today, [far, near_up, near_dn], k=2)
    assert [d["date"] for d in out["days"]] == ["2026-01-01", "2026-02-05"]
    assert out["through"] == "11:15" and out["rose_after"] == 1 and out["fell_after"] == 1
    assert out["days"][0]["after"] == round((60 - (-205)) / 20000 * 100 * 220, 1)       # scaled to today's open
    assert "not a forecast" in out["note"]


def test_before_the_first_hour_there_is_nothing_to_match():
    assert wp.similar({"open": 22000.0, "path": {}, "now": 5.0}, [_row(date(2026, 1, 1), True, 1, 1, 1)]) is None


def test_the_why_lines_use_a_true_minus_sign():
    rows = [_row(date(2026, 9, 1), True, 100, 80, -20)] * 40
    for k, r in enumerate(rows):
        rows[k] = {**r, "gap_pct": 0.1 + 0.01 * (k % 3), "now": -10.0 - (k % 5)}
    text = " ".join(wp.why(rows, rows))
    assert "-0." not in text and "−" in text
