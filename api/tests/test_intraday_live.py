"""The Today tab's intraday rules: the live follower must make the study's own
trades, see nothing it could not have seen at the time, write "Consider"
only for an APPROVED rule, and record each trigger once, at a real price,
in a record that cannot be edited."""

import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import backtest.nifty_pipeline as npl
import briefing.intraday_live as live
from backtest.course_strategies import Series
from market_data.base import Candle
from storage import intraday_forward_db as fwd

SLOTS_5M = pd.timedelta_range("09:15:00", "15:25:00", freq="5min")


def walk(n_days: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ds = [d.date().isoformat() for d in pd.bdate_range("2025-01-01", periods=n_days)]
    stamps = pd.DatetimeIndex([pd.Timestamp(d) + t for d in ds for t in SLOTS_5M]).tz_localize("Asia/Kolkata")
    close = 20000 * np.exp(np.cumsum(rng.normal(0, 0.0012, len(stamps))))
    opn = np.r_[20000, close[:-1]] * np.exp(rng.normal(0, 0.0003, len(stamps)))
    hi = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.0004, len(stamps))))
    lo = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.0004, len(stamps))))
    return pd.DataFrame({"open": opn, "high": hi, "low": lo, "close": close}, index=stamps)


STUDY = {"noise_band": lambda s: npl.noise_band(s, {}), "last_half_hour": lambda s: npl.last_half_hour(s, {}),
         "opening_range_5m": npl.opening_range_5m}


@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("name", live.RULES)
def test_on_a_finished_day_the_live_follower_makes_the_studys_trade(name, seed):
    df = walk(30, seed)
    s = Series(df)
    study = {pd.Timestamp(t["entry_ts"]).date(): t for t in STUDY[name](s)}
    compared = 0
    for day in s.sessions[1:]:
        st = live.FOLLOW[name](s, {}, day)
        t = study.get(day)
        if t is None:
            assert st["status"] in ("no_trade", "no_history")
            continue
        compared += 1
        assert st["status"] == "closed"
        assert (st["side"], st["entry_at"], st["entry_index"], st["exit_at"], st["exit_index"], st["exit_reason"]) == \
            (t["side"], t["entry_ts"], t["entry"], t["exit_ts"], t["exit"], t["reason"])
    assert compared >= 5


@pytest.mark.parametrize("name", live.RULES)
def test_part_way_through_the_day_it_knows_only_what_has_closed(name):
    """Cut the day after every bar: the rule has triggered exactly when the
    study's entry bar is among the closed ones, on the same side."""
    df = walk(22, seed=4)
    full = Series(df)
    study = {pd.Timestamp(t["entry_ts"]).date(): t for t in STUDY[name](full)}
    days = [d for d in full.sessions[15:] if d in study][:3]
    assert days
    for day in days:
        b0, b1 = full.bounds[day]
        t = study[day]
        for cut in range(b0, b1 + 1):
            st = live.FOLLOW[name](Series(df.iloc[:cut + 1]), {}, day)
            if cut >= t["entry_i"]:
                assert st["status"] in ("in_trade", "closed") and st["side"] == t["side"]
                assert st["entry_at"] == t["entry_ts"]
                if st["status"] == "closed":
                    assert st["exit_at"] == t["exit_ts"]
            else:
                assert st["status"] not in ("in_trade", "closed")


def test_a_bar_still_forming_is_not_used():
    now = datetime(2026, 10, 1, 10, 7, tzinfo=live.IST)
    candles = [Candle(timestamp=f"2026-10-01T{h}:00+05:30", open=1, high=1, low=1, close=1)
               for h in ("09:55", "10:00", "10:05")]
    df = live._frame(candles, now)
    assert [ts.strftime("%H:%M") for ts in df.index] == ["09:55", "10:00"]   # 10:05 closes at 10:10


def test_the_contract_is_the_nearest_expiry_not_expiring_that_day_at_the_money():
    exp = [date(2026, 10, 6), date(2026, 10, 13)]
    assert live.contract(1, 22624.0, date(2026, 10, 1), exp) == {"expiry": "2026-10-06", "strike": 22600,
                                                                  "option_type": "CE"}
    assert live.contract(-1, 22626.0, date(2026, 10, 6), exp) == {"expiry": "2026-10-13", "strike": 22650,
                                                                   "option_type": "PE"}
    assert live.contract(1, 22600.0, date(2026, 10, 13), exp) is None


REJECTED = {"verdict": "REJECTED", "holdout_t": 1.57, "required_t": 3.19}
APPROVED = {"verdict": "APPROVED", "holdout_t": 3.5, "required_t": 3.19}
IN_TRADE = {"status": "in_trade", "side": 1, "entry_at": "2026-10-01T10:10:00+05:30", "entry_time": "10:15",
            "contract": {"expiry": "2026-10-06", "strike": 22600, "option_type": "CE"}}
CLOSED = {**IN_TRADE, "status": "closed", "exit_time": "11:15", "exit_reason": "back inside"}
WAITING = {"status": "waiting", "next": {"at": "10:45"}}


@pytest.mark.parametrize("st", [IN_TRADE, CLOSED, WAITING, {"status": "no_trade"}, {"status": "no_history"}])
@pytest.mark.parametrize("verdict", [REJECTED, None, {"verdict": "CONDITIONAL", "holdout_t": 2.0, "required_t": 3.2}])
def test_consider_is_never_written_for_a_rule_that_was_not_approved(st, verdict):
    text = live.line("Noise-band momentum", st, verdict)
    assert "Consider" not in text and "buy" not in text.lower()


def test_a_rejected_trigger_says_it_is_not_a_trade_and_why():
    text = live.line("Noise-band momentum", CLOSED, REJECTED)
    assert text.startswith("No intraday trade: Noise-band momentum triggered at 10:15 on the call side")
    assert "holdout t 1.57 against 3.19" in text and "not a trade" in text


def test_only_an_approved_rule_in_a_trade_is_worded_as_something_to_consider():
    assert live.line("Noise-band momentum", IN_TRADE, APPROVED) == \
        "Consider buying NIFTY 06 Oct 22,600 CE — Noise-band momentum, holdout t 3.5."
    assert "Consider" not in live.line("Noise-band momentum", CLOSED, APPROVED)   # over: nothing to consider


# --- the forward record ----------------------------------------------------------------

def state(status="in_trade", session="2026-10-01"):
    rule = {"name": "opening_range_5m", "status": status, "side": 1, "entry_at": "2026-10-01T09:15:00+05:30",
            "entry_index": 22610.0, "contract": {"expiry": "2026-10-06", "strike": 22600, "option_type": "CE"}}
    if status == "closed":
        rule.update(exit_at="2026-10-01T11:00:00+05:30", exit_index=22580.0, exit_reason="stop")
    return {"session": session, "source": "Kite", "rules": [rule]}


def chain(taken_at, bid, ask):
    return [{"taken_at": taken_at, "expiry": "2026-10-06", "strike": 22600.0, "option_type": "CE",
             "bid": bid, "ask": ask, "ltp": (bid + ask) / 2},
            {"taken_at": taken_at, "expiry": "2026-10-06", "strike": 22600.0, "option_type": "PE",
             "bid": 1.0, "ask": 2.0, "ltp": 1.5}]


def test_an_entry_is_recorded_once_at_the_chains_ask_and_bid(tmp_path):
    path = tmp_path / "intraday.db"
    now = datetime(2026, 10, 1, 9, 20, 20, tzinfo=live.IST)
    assert live.record(now, chain("2026-10-01T09:20:05", 118.5, 120.0), state(), path) == ["opening_range_5m entry"]
    assert live.record(now, chain("2026-10-01T09:25:05", 130.0, 131.0), state(), path) == []
    e = fwd.events("2026-10-01", path)[0]
    assert (e["kind"], e["bar_close_at"][:16], e["ask"], e["bid"], e["option_type"]) == \
        ("entry", "2026-10-01T09:20", 120.0, 118.5, "CE")


def test_the_exit_follows_the_entry_and_the_trade_is_counted_when_both_are_on_time(tmp_path):
    path = tmp_path / "intraday.db"
    live.record(datetime(2026, 10, 1, 9, 20, 20, tzinfo=live.IST), chain("2026-10-01T09:20:05", 118.5, 120.0),
                state(), path)
    wrote = live.record(datetime(2026, 10, 1, 11, 5, 20, tzinfo=live.IST), chain("2026-10-01T11:05:10", 90.0, 91.0),
                        state("closed"), path)
    assert wrote == ["opening_range_5m exit"]
    [t] = fwd.trades(path)
    assert t["counted"] and t["return_pct"] == round((90.0 / 120.0 - 1) * 100, 2)
    assert fwd.summary(path)["opening_range_5m"]["trades"] == 1


def test_a_price_taken_well_after_the_bar_is_kept_but_not_counted(tmp_path):
    path = tmp_path / "intraday.db"
    live.record(datetime(2026, 10, 1, 9, 40, 20, tzinfo=live.IST), chain("2026-10-01T09:40:05", 118.5, 120.0),
                state("closed"), path)                        # first seen twenty minutes late
    [t] = fwd.trades(path)
    assert not t["counted"] and t["entry_late_s"] > fwd.ON_TIME_S


def test_nothing_is_written_without_a_price_or_for_another_session(tmp_path):
    path = tmp_path / "intraday.db"
    now = datetime(2026, 10, 1, 9, 20, 20, tzinfo=live.IST)
    assert live.record(now, [], state(), path) == []
    assert live.record(now, chain("2026-10-01T09:20:05", 1, 2), state(session="2026-09-30"), path) == []
    assert fwd.events(db_path=path) == []


def test_the_record_refuses_to_be_edited(tmp_path):
    path = tmp_path / "intraday.db"
    live.record(datetime(2026, 10, 1, 9, 20, 20, tzinfo=live.IST), chain("2026-10-01T09:20:05", 118.5, 120.0),
                state(), path)
    conn = sqlite3.connect(path)
    for sql in ("UPDATE events SET ask = 1", "DELETE FROM events"):
        with pytest.raises(sqlite3.DatabaseError, match="never edited"):
            conn.execute(sql)
    conn.close()
    assert fwd.events(db_path=path)[0]["ask"] == 120.0


def test_the_tick_prices_only_contracts_a_rule_bought_today():
    s = {"rules": [{"name": "noise_band", "status": "waiting"},
                   {"name": "opening_range_5m", "status": "closed",
                    "contract": {"expiry": "2026-10-06", "strike": 22600, "option_type": "CE"}}]}
    assert live.tick_contracts(s) == [{"id": "iopening_range_5m", "underlying": "NIFTY", "expiry": "2026-10-06",
                                       "strike": 22600, "option_type": "CE"}]
    assert live.tick_contracts(None) == []


def test_evaluate_reports_the_last_session_with_every_rule(monkeypatch):
    monkeypatch.setattr(live, "verdicts", lambda: {"noise_band": REJECTED})
    df = walk(20, seed=9)
    last = df.index[-1].date()
    out = live.evaluate(df, {}, [last + timedelta(days=3)])
    assert out["session"] == last.isoformat() and out["bars_through"] == "15:30"
    assert [r["name"] for r in out["rules"]] == list(live.RULES)
    assert all(r["line"] and "Consider" not in r["line"] for r in out["rules"])


# --- a session missing from the 5-minute bars ------------------------------------------

def closes_of(df: pd.DataFrame) -> dict:
    return {d: float(g["close"].iloc[-1]) for d, g in df.groupby(df.index.date)}


def test_the_previous_close_comes_from_the_daily_archive_when_a_days_bars_are_missing():
    """At midnight on 1 Oct 2026 Kite stopped serving 30 Sep's 5-minute bars:
    the session before in the bars was 29 Sep, a day too far back."""
    df = walk(20, seed=5)
    closes = closes_of(df)
    days = sorted(closes)
    gone, day = days[-2], days[-1]
    s = Series(df[df.index.date != gone])
    st = live.last_half_hour_now(s, closes, day)
    i45 = df.index.get_loc(df[(df.index.date == day)].between_time("09:40", "09:40").index[0])
    assert st["previous_close"] == round(closes[gone], 2)
    assert st["first_half_hour_pts"] == round(float(df["close"].iloc[i45] - closes[gone]), 2)


def test_the_noise_band_will_not_set_levels_over_a_missing_session():
    df = walk(20, seed=5)
    closes = closes_of(df)
    days = sorted(closes)
    st = live.noise_band_now(Series(df[df.index.date != days[-3]]), closes, days[-1])
    assert st == {"status": "no_history", "missing": [days[-3].isoformat()]}
    assert "5-minute bars for" in live.line("Noise-band momentum", st, REJECTED)


def test_a_last_session_missing_from_the_bars_is_named(monkeypatch):
    monkeypatch.setattr(live, "verdicts", lambda: {})
    df = walk(20, seed=5)
    closes = closes_of(df)
    last = sorted(closes)[-1]
    out = live.evaluate(df[df.index.date != last], closes, [last + timedelta(days=7)])
    assert out["missing_after"] == [last.isoformat()] and out["session"] < last.isoformat()


def test_sessions_kite_did_not_serve_are_filled_from_yahoo(monkeypatch):
    import market_data.bar_archive as ba
    import market_data.yfinance_provider as yp
    import market_data.zerodha_provider as zp
    df = walk(6, seed=8)
    days = sorted(set(df.index.date))

    def candles(frame):
        return [Candle(timestamp=ts.isoformat(), open=r.open, high=r.high, low=r.low, close=r.close)
                for ts, r in frame.iterrows()]

    class Archive:
        def get_ohlc(self, *a):
            return candles(df[df.index.date <= days[1]])

    class Kite:
        def get_ohlc(self, *a, **k):
            return candles(df[(df.index.date > days[1]) & (df.index.date != days[3])])   # skips days[3]

    class Yahoo:
        def get_ohlc(self, sym, tf, start, end):
            return candles(df[(df.index.date >= start) & (df.index.date < end)])

    monkeypatch.setattr(ba, "ArchiveProvider", Archive)
    monkeypatch.setattr(zp, "ZerodhaProvider", Kite)
    monkeypatch.setattr(yp, "YFinanceProvider", Yahoo)
    now = datetime.combine(days[-1] + timedelta(days=1), datetime.min.time(), tzinfo=live.IST)
    bars, source = live.five_minute_bars(now, closes_of(df))
    assert sorted(set(bars.index.date)) == days
    assert source == f"Kite, and Yahoo for {days[3].day} {days[3]:%b}"
    assert len(bars) == len(df)
