"""Today's breakout levels. What must hold: every level comes from data that
existed before it is used; a break is a 5-minute close across a level, and a
session that opens beyond one has not broken it; a break that closes back
within 30 minutes failed; each break is scored at fixed times after it; the
record is measured the same way over history as live; and the forward record
is written once, priced from the chain saved in the same run, never edited."""

import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import briefing.breakout_levels as bl
from market_data.kite_session import IST

DAY = date(2026, 10, 6)


def bars(closes, day=DAY, open_=None, spread=2.0):
    """A session of 5-minute bars from 09:15, closes given; highs/lows around them."""
    idx = pd.DatetimeIndex([pd.Timestamp(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)) +
                            timedelta(minutes=5 * i) for i in range(len(closes))])
    opens = [open_ if open_ is not None else closes[0]] + list(closes[:-1])
    return pd.DataFrame({"open": opens, "high": [max(o, c) + spread for o, c in zip(opens, closes)],
                         "low": [min(o, c) - spread for o, c in zip(opens, closes)], "close": closes}, index=idx)


DAILY = {date(2026, 9, 28): {"open": 100, "high": 110, "low": 95, "close": 105},
         date(2026, 9, 29): {"open": 105, "high": 120, "low": 100, "close": 118},
         date(2026, 10, 1): {"open": 118, "high": 125, "low": 112, "close": 115},
         date(2026, 10, 5): {"open": 115, "high": 130, "low": 108, "close": 128}}


def test_the_days_levels_come_from_earlier_sessions_and_the_opening_range_from_its_first_15_minutes():
    lv = {x["key"]: x["price"] for x in bl.day_levels(DAILY, DAY, bars([129, 131, 127, 133]), {"fch": 140.0})}
    assert (lv["pdh"], lv["pdl"], lv["pdc"]) == (130, 108, 128)          # Monday 5 Oct
    assert (lv["pwh"], lv["pwl"]) == (125, 95)                             # the week of 28 Sep
    assert (lv["orh"], lv["orl"]) == (131 + 2, 127 - 2)                    # first three bars' range
    assert lv["fch"] == 140.0
    early = {x["key"] for x in bl.day_levels(DAILY, DAY, bars([129, 131]), {})}
    assert "orh" not in early                                              # not known before 09:30


def test_a_break_is_a_five_minute_close_across_the_level():
    ev = bl.breaks("pdh", 130.0, bars([126, 128, 131, 133, 132]), start=0)
    assert [(e["direction"], e["at"]) for e in ev] == [("up", "09:30")]   # the 09:25 bar closed 131


def test_opening_beyond_a_level_is_not_breaking_it():
    ev = bl.breaks("pdh", 130.0, bars([134, 135, 136], open_=133.0), start=0)
    assert ev == []
    back = bl.breaks("pdh", 130.0, bars([134, 129, 131], open_=133.0), start=0)
    assert [e["direction"] for e in back] == ["down", "up"]


def test_the_opening_range_is_only_broken_after_it_is_set():
    b = bars([129, 135, 127, 136, 137])                                    # 2nd bar is above the eventual high? no: it sets it
    orh = max(b["high"].iloc[:3])
    ev = bl.breaks("orh", orh, b, start=bl.OR_BARS)
    assert all(e["i"] >= bl.OR_BARS for e in ev)


def test_a_break_that_closes_back_within_30_minutes_failed():
    held = bl.breaks("pdh", 130.0, bars([128, 131] + [133] * 14), start=0)[0]
    gave_back = bl.breaks("pdh", 130.0, bars([128, 131, 132, 129] + [128] * 12), start=0)[0]
    b1, b2 = bars([128, 131] + [133] * 14), bars([128, 131, 132, 129] + [128] * 12)
    assert bl.outcome(held, b1)["failed"] is False
    assert bl.outcome(gave_back, b2)["failed"] is True


def test_each_break_is_scored_at_fixed_times_after_it():
    b = bars([128, 131] + [131 + i for i in range(1, 74)])                 # a full session, rising a point a bar
    e = bl.breaks("pdh", 130.0, b, start=0)[0]
    o = bl.outcome(e, b)
    assert o["pts_15"] == pytest.approx(4.0) and o["pts_30"] == pytest.approx(7.0) and o["pts_60"] == pytest.approx(13.0)
    assert o["held_30"] and o["pts_close"] == pytest.approx(float(b["close"].iloc[-1]) - 130.0)
    short = bars([128, 131, 133])
    o2 = bl.outcome(bl.breaks("pdh", 130.0, short, start=0)[0], short)
    assert o2["pts_30"] is None and o2["pts_close"] is None                # not known yet


def test_a_downward_break_is_scored_in_its_own_direction():
    b = bars([110, 107] + [107 - i for i in range(1, 20)])
    e = bl.breaks("pdl", 108.0, b, start=0)[0]
    assert e["direction"] == "down" and bl.outcome(e, b)["pts_15"] == pytest.approx(4.0)


def test_each_levels_state_now():
    b = bars([126, 128, 129.5, 128])                                       # high reaches 131.5 across 130
    assert bl.state(130.0, b, [], start=0)["state"] == "tested"
    assert bl.state(150.0, b, [], start=0)["state"] == "untouched"
    up = bars([128, 131, 133])
    ev = bl.breaks("pdh", 130.0, up, start=0)
    assert bl.state(130.0, up, ev, start=0)["state"] == "broken up"


def test_the_record_counts_how_often_breaks_held_overall_and_lately():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(100)]
    evs = [{"level": "pdh", "direction": "up", "day": d.isoformat(),
            "outcome": {"held_30": i % 2 == 0, "failed": i % 4 == 1, "pts_30": 10.0 if i % 2 == 0 else -5.0,
                        "pts_close": 3.0}} for i, d in enumerate(days)]
    st = bl.stats(evs, recent_sessions=60)["pdh"]["up"]
    assert st["all"]["n"] == 100 and st["all"]["held_30_pct"] == 50.0 and st["all"]["failed_pct"] == 25.0
    assert st["recent"]["n"] == 60 and st["all"]["median_pts_30"] == pytest.approx(2.5)


def test_history_uses_only_what_existed_before_each_break():
    b = pd.concat([bars([100 + i for i in range(75)], day=date(2026, 10, 1)),
                   bars([128, 131] + [133] * 73, day=date(2026, 10, 5))])
    daily = {date(2026, 9, 29): {"open": 100, "high": 120, "low": 100, "close": 118},
             date(2026, 10, 1): {"open": 100, "high": 174, "low": 98, "close": 174},
             date(2026, 10, 5): {"open": 128, "high": 135, "low": 126, "close": 133}}
    hist = bl.history(b, daily, {})
    mon = [e for e in hist if e["day"] == "2026-10-05"]
    assert all(e["level_price"] != 135 for e in mon)                       # never the session's own high
    later = dict(daily)
    later[date(2026, 10, 5)] = {**daily[date(2026, 10, 5)], "high": 999}
    assert bl.history(b, later, {}) == hist                                # a session's own range changes nothing


# --- the forward record -----------------------------------------------------------

def _chain(stamp, strike=22550.0, expiry="2026-10-13"):
    return [{"taken_at": stamp, "expiry": expiry, "strike": strike, "option_type": t, "bid": 99.0, "ask": 100.0,
             "ltp": 99.5} for t in ("CE", "PE")]


def test_a_break_is_recorded_once_at_the_chains_price_and_never_edited(tmp_path):
    db = tmp_path / "b.db"
    state = {"session": DAY.isoformat(), "levels": [{"key": "pdh", "price": 22540.0, "events": [
        {"level": "pdh", "direction": "up", "at": "10:15", "bar_close_at": "2026-10-06T10:15:00+05:30",
         "close": 22555.0, "level_price": 22540.0}]}]}
    now = datetime(2026, 10, 6, 10, 16, tzinfo=IST)
    listed = [date(2026, 10, 6), date(2026, 10, 13)]
    early = bl.record(now, _chain("2026-10-06T10:13:00"), state, listed, db)          # chain from before the bar
    assert early == []
    w = bl.record(now, _chain("2026-10-06T10:15:40"), state, listed, db)
    assert w == ["pdh up 10:15"]
    assert bl.record(now, _chain("2026-10-06T10:20:40"), state, listed, db) == []     # once
    from storage import breakout_db
    row = breakout_db.events(DAY.isoformat(), db)[0]
    assert (row["option_type"], row["strike"], row["expiry"], row["ask"]) == ("CE", 22550.0, "2026-10-13", 100.0)
    conn = sqlite3.connect(db)
    for sql in ("UPDATE events SET ask = 1", "DELETE FROM events"):
        with pytest.raises(sqlite3.DatabaseError, match="never edited"):
            conn.execute(sql)
    conn.close()


def test_the_option_move_after_a_break_is_bought_at_the_ask_and_sold_at_the_bid():
    ev = {"bar_close_at": "2026-10-06T10:15:00+05:30", "ask": 100.0, "expiry": "2026-10-13", "strike": 22550.0,
          "option_type": "CE"}
    snaps = [{"taken_at": "2026-10-06T10:30:30", "bid": 108.0, "ask": 109.0},
             {"taken_at": "2026-10-06T10:45:20", "bid": 95.0, "ask": 96.0},
             {"taken_at": "2026-10-06T11:40:00", "bid": 120.0, "ask": 121.0}]
    m = bl.option_moves(ev, snaps)
    assert m["pct_15"] == pytest.approx(8.0) and m["pct_30"] == pytest.approx(-5.0)
    assert m["pct_60"] is None                                             # no snapshot within 6 minutes of 11:15


def test_a_recorded_break_is_scored_once_its_session_is_over(tmp_path):
    from storage import breakout_db
    db = tmp_path / "b.db"
    session = bars([22530.0, 22555.0] + [22555.0 + i for i in range(1, 74)])
    closed = (session.index[1] + timedelta(minutes=5)).isoformat()
    breakout_db.add_event({"trade_day": DAY.isoformat(), "level": "pdh", "direction": "up", "bar_close_at": closed,
                           "level_price": 22540.0, "index_level": 22555.0, "expiry": "2026-10-13", "strike": 22550.0,
                           "option_type": "CE", "price_at": "2026-10-06T09:25:40", "bid": 99.0, "ask": 100.0,
                           "ltp": 99.5, "on_time": 1, "recorded_at": "2026-10-06T09:26:00+05:30"}, db)
    snaps = [{"taken_at": "2026-10-06T09:40:30", "bid": 110.0, "ask": 111.0}]
    during = datetime(2026, 10, 6, 11, 0, tzinfo=IST)
    assert bl.score_forward(during, {DAY: session.iloc[:20]}, lambda e: snaps, db) == []   # not over yet
    after = datetime(2026, 10, 6, 20, 0, tzinfo=IST)
    assert bl.score_forward(after, {DAY: session}, lambda e: snaps, db) == ["2026-10-06 pdh up"]
    o = breakout_db.events(DAY.isoformat(), db)[0]["outcome"]
    assert o["pts_15"] == pytest.approx(18.0) and o["pct_15"] == pytest.approx(10.0)
    assert bl.score_forward(after, {DAY: session}, lambda e: snaps, db) == []              # once


def test_random_levels_measured_the_same_way_are_the_yardstick():
    """Any line a 5-minute close crosses is already a few points behind price,
    so 'held 30 minutes 60% of the time' means little alone; random levels
    near the last close, scored the same way, are what a level has to beat."""
    b = pd.concat([bars([100 + (i % 7) for i in range(75)], day=date(2026, 10, 1)),
                   bars([105 + (i % 9) for i in range(75)], day=date(2026, 10, 5))])
    daily = {date(2026, 9, 29): {"open": 100, "high": 108, "low": 99, "close": 104},
             date(2026, 10, 1): {"open": 100, "high": 107, "low": 99, "close": 106},
             date(2026, 10, 5): {"open": 105, "high": 114, "low": 104, "close": 110}}
    first = bl.baseline_history(b, daily)
    assert first == bl.baseline_history(b, daily)                         # the same every night
    assert first and all(e["level"] == "baseline" for e in first)
    for e in first:
        prev_close = 104 if e["day"] == "2026-10-01" else 106
        assert abs(e["level_price"] - prev_close) <= prev_close * bl.BASELINE_SPAN
    st = bl.stats(first)
    assert "baseline" in st


def test_the_api_serves_the_levels_and_the_job_rebuilds_the_record_after_the_forecast(monkeypatch):
    import importlib.util
    from pathlib import Path

    import main
    monkeypatch.setattr("briefing.breakout_levels.build_breakouts", lambda: {"session": "2026-10-07", "levels": []})
    from cache import _CACHE
    _CACHE.pop("breakouts", None)
    assert main.breakouts()["session"] == "2026-10-07"
    spec = importlib.util.spec_from_file_location("dj", Path(__file__).parents[1] / "scripts" / "daily_job.py")
    dj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dj)
    order = dj.RETRY_AT_END
    assert order.index("day-ahead forecast") < order.index("breakout levels")


def test_the_freshness_check_watches_the_levels_and_their_record():
    import briefing.freshness as fr
    keys = {s.key: s for s in fr.SOURCES}
    assert keys["breakouts"].kind == "live" and keys["breakout_record"].fix == ("breakouts",)


def test_a_level_the_session_opened_beyond_says_so():
    st = bl.state(130.0, bars([134, 135, 136], open_=133.0), [], start=0)
    assert st["state"] == "untouched" and st["opened"] == "above"
    assert bl.state(140.0, bars([134, 135, 136], open_=133.0), [], start=0)["opened"] == "below"


# --- how far price went after a break --------------------------------------------------

def test_travel_is_the_furthest_price_went_the_breaks_way_from_the_breaking_close():
    b = bars([128, 131] + [131 + i for i in range(1, 74)])                 # rising a point a bar, highs +2
    o = bl.outcome(bl.breaks("pdh", 130.0, b, start=0)[0], b)
    # from the 131 close: the next bar's high is 132 + 2; three bars on, 134 + 2
    assert o["travel_5"] == pytest.approx(3.0) and o["travel_15"] == pytest.approx(5.0)
    assert o["travel_30"] == pytest.approx(8.0) and o["travel_60"] == pytest.approx(14.0)
    down = bars([110, 107] + [107 - i for i in range(1, 20)])
    od = bl.outcome(bl.breaks("pdl", 108.0, down, start=0)[0], down)
    assert od["travel_5"] == pytest.approx(3.0)                            # 107 to the next low, 106 - 2
    short = bars([128, 131, 133])
    assert bl.outcome(bl.breaks("pdh", 130.0, short, start=0)[0], short)["travel_15"] is None


def test_a_session_is_classed_by_how_it_opened():
    assert bl.open_class(100.3, 100.0) == "gap up" and bl.open_class(99.7, 100.0) == "gap down"
    assert bl.open_class(100.1, 100.0) == "flat" and bl.open_class(99.85, 100.0) == "flat"


def test_history_carries_each_sessions_open():
    b = pd.concat([bars([100 + i for i in range(75)], day=date(2026, 10, 1)),
                   bars([128, 131] + [133] * 73, day=date(2026, 10, 5))])
    daily = {date(2026, 9, 29): {"open": 100, "high": 120, "low": 100, "close": 118},
             date(2026, 10, 1): {"open": 100, "high": 174, "low": 98, "close": 174},
             date(2026, 10, 5): {"open": 128, "high": 135, "low": 126, "close": 133}}
    hist = bl.history(b, daily, {})
    assert {e["open"] for e in hist if e["day"] == "2026-10-01"} == {"gap down"}   # 100 against 118
    assert {e["open"] for e in bl.baseline_history(b, daily) if e["day"] == "2026-10-01"} == {"gap down"}


def _ev(level, d, travel, open_="gap up", close=20000.0):
    return {"level": level, "direction": d, "open": open_, "close": close,
            "outcome": {f"travel_{m}": travel for m in bl.TRAVEL_MIN}}


def test_the_odds_of_a_move_are_counted_exactly_at_todays_price_for_every_size():
    # four breaks at 20,000 that travelled 0.1%, 0.2%, 0.3%, 0.4%: 20, 40, 60, 80 points then
    evs = [_ev("pdh", "up", 20000 * p / 100) for p in (0.1, 0.2, 0.3, 0.4)]
    table = bl.travel_table(evs)
    od = bl.odds(table, "pdh", "up", "gap up", price=25000.0)               # at 25,000 those are 25..100 pts
    i = {t: k for k, t in enumerate(bl.TARGETS)}
    assert od["all"]["n"]["30"] == 4
    assert od["all"]["pct"]["30"][i[20]] == 100.0 and od["all"]["pct"]["30"][i[30]] == 75.0
    assert od["all"]["pct"]["30"][i[100]] == 25.0 and od["all"]["pct"]["30"][i[110]] == 0.0
    assert od["like_today"]["n"]["30"] == 4
    assert bl.odds(table, "pdh", "up", "gap down", price=25000.0)["like_today"]["n"]["30"] == 0


def test_a_level_stands_out_only_when_it_beats_random_lines_well_beyond_chance():
    assert bl.compare(60.0, 400, 40.0, 4000) == "more often than random"
    assert bl.compare(20.0, 400, 40.0, 4000) == "less often than random"
    assert bl.compare(44.0, 400, 40.0, 4000) == "like random"              # inside chance at this size
    assert bl.compare(90.0, 10, 40.0, 4000) == "too few breaks"


def test_each_level_says_in_plain_words_where_it_is_and_what_happened_today():
    lv = {"key": "pdh", "label": "Yesterday's high", "price": 22621.8, "distance_pts": 154.3,
          "state": "broken up", "since": "09:50", "failed": False, "opened": "below", "events": []}
    p = bl.plain(lv)
    assert p["where"] == "154 pts below NIFTY" and p["watch"] == "up"     # today's break, not the way back
    assert p["today"] == "Crossed upward at 09:50 and still above"
    p2 = bl.plain({**lv, "distance_pts": -40.0, "state": "untouched", "since": None, "opened": "below"})
    assert p2["where"] == "40 pts above NIFTY" and p2["watch"] == "up" and p2["today"] == "Not reached today"
    p3 = bl.plain({**lv, "state": "broken up", "failed": True})
    assert p3["today"] == "Crossed upward at 09:50, then closed back within 30 minutes"


def test_a_level_further_than_the_random_lines_is_marked():
    lv = {x["key"]: x for x in bl.evaluate(bars([129, 131, 127, 133]), DAILY, DAY, {"oip": 100.0})["levels"]}
    assert lv["oip"]["beyond_random"] and not lv["pdc"]["beyond_random"]  # 100 is 22% from the 128 close


# --- support and resistance, the two key levels, the entry check ----------------------

def test_the_days_floor_pivots_come_from_the_previous_session():
    lv = {x["key"]: x["price"] for x in bl.day_levels(DAILY, DAY, bars([129, 131, 127, 133]), {})}
    # 5 Oct: high 130, low 108, close 128 -> P 122, R1 136, S1 114, R2 144, S2 100
    assert (lv["pp"], lv["r1"], lv["s1"], lv["r2"], lv["s2"]) == (122, 136, 114, 144, 100)


def test_levels_at_the_same_price_are_one_row():
    rows = bl.merge_same_price([{"key": "pdh", "label": "Yesterday's high", "price": 22776.1},
                                {"key": "pdc", "label": "Yesterday's close", "price": 22776.1},
                                {"key": "orh", "label": "Opening range high", "price": 22692.95}])
    assert [r["label"] for r in rows] == ["Yesterday's high & close", "Opening range high"]
    assert rows[0]["keys"] == ["pdh", "pdc"]


def test_the_key_levels_are_the_nearest_above_and_below_nifty():
    levels = [{"key": "pdh", "label": "Yesterday's high", "price": 22776.1},
              {"key": "orh", "label": "Opening range high", "price": 22692.95},
              {"key": "orl", "label": "Opening range low", "price": 22600.45},
              {"key": "pdl", "label": "Yesterday's low", "price": 22561.6}]
    k = bl.key_levels(levels, 22603.05)
    assert k["resistance"]["key"] == "orh" and k["support"]["key"] == "orl"
    assert bl.key_levels(levels, 23000.0)["resistance"] is None


def test_the_entry_odds_are_counted_at_the_exact_move_needed():
    evs = [{"level": "orh", "direction": "up", "open": "flat", "close": 20000.0,
            "outcome": {f"travel_{m}": 20000 * p / 100 for m in bl.TRAVEL_MIN}} for p in (0.1, 0.2, 0.3, 0.4)]
    evs += [{"level": "baseline", "direction": "up", "open": "flat", "close": 20000.0,
             "outcome": {f"travel_{m}": 20000 * p / 100 for m in bl.TRAVEL_MIN}} for p in (0.1, 0.1, 0.4, 0.4)]
    table = bl.travel_table(evs)
    o = bl.entry_odds(table, "orh", "up", need_pts=37.0, price=25000.0, minutes=30)  # 25, 50, 75, 100 pts at 25,000
    assert o["pct"] == 75.0 and o["n"] == 4 and o["random_pct"] == 50.0 and o["random_n"] == 4
    assert o["verdict"] == "few"                                                    # too few breaks to judge


def test_the_entry_check_prices_the_atm_option_and_counts_the_odds_for_each_window():
    levels = [{"key": "orh", "label": "Opening range high", "price": 22692.95},
              {"key": "orl", "label": "Opening range low", "price": 22600.45}]
    evs = [{"level": k, "direction": d, "open": "flat", "close": 22600.0,
            "outcome": {f"travel_{m}": 22600 * p / 100 for m in bl.TRAVEL_MIN}}
           for k, d in (("orh", "up"), ("orl", "down"), ("baseline", "up"), ("baseline", "down"))
           for p in (0.05, 0.1, 0.2, 0.3)]
    table = bl.travel_table(evs)
    row = {"strike": 22600.0, "is_atm": True,
           "call": {"bid": 99.0, "ask": 100.0, "ltp": 99.5}, "put": {"bid": 89.0, "ask": 90.0, "ltp": 89.5}}
    chain = {"expiry": "13-Oct-2026", "rows": [row], "lot_size": 65, "underlying_value": 22603.05}
    now = datetime(2026, 10, 7, 11, 0, tzinfo=IST)
    e = bl.entry_check(levels, 22603.05, table, now, chain=chain, holidays=set())
    up, down = e["resistance"], e["support"]
    assert up["key"] == "orh" and up["direction"] == "up" and up["option"]["kind"] == "CE"
    assert down["option"]["kind"] == "PE" and down["option"]["premium"] == 90.0
    assert set(up["windows"]) == {"15", "30", "60"}
    w = up["windows"]["30"]
    assert w["need_pts"] > 0 and w["n"] == 4 and w["random_n"] == 4 and w["verdict"] == "few"
    assert up["windows"]["15"]["need_pts"] < up["windows"]["60"]["need_pts"]  # longer wait, more decay to beat


def test_the_entry_check_and_the_key_levels_are_watched_for_staleness():
    import briefing.freshness as fr
    keys = {s.key: s for s in fr.SOURCES}
    assert keys["breakout_entry"].path == "/api/breakouts" and keys["breakout_entry"].fields == ("entry_as_of",)
    assert keys["breakout_entry"].kind == "live" and keys["breakout_entry"].max_age_min == 10
