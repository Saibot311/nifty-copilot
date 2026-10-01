"""The forward harness for order-flow rules, on made-up sessions: it buys at
the ask after the snapshot it decided on and sells at the bid, charges the
rate card without the assumed slippage, compares with the same option bought
with no signal, and will not judge a sample that is too small or still open."""

import random
from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

import backtest.orderflow_forward as fw
import briefing.intraday_live as live
from backtest.walkforward import welch_t_stat
from storage import option_snapshots_db
from tests.test_orderflow_features import chain

FAR = "2026-12-29"
FIRST, LAST = 9 * 60 + 20, 15 * 60 + 30


def session(day: date, path, expiry: str = FAR, drop=(), over=None) -> list[dict]:
    """A snapshot every five minutes from 09:20 to 15:30, NSE-stamped ten
    seconds past; `path(minute)` is the index, `over(minute)` overrides rows."""
    rows = []
    for m in range(FIRST, LAST + 1, 5):
        clock = f"{m // 60:02d}:{m % 60:02d}"
        if clock not in drop:
            rows += chain(f"{clock}:10", path(m), expiry=expiry, day=day, over=over(m) if over else None)
    return rows


def flat(_m):
    return 22500.0


def days(n: int, first: str = "2026-10-05") -> list[date]:
    return [d.date() for d in pd.bdate_range(first, periods=n)]


def at_eleven(side):
    """Decides once, on the first snapshot at or after 11:00."""
    def decide(hist, _bars):
        t = datetime.fromisoformat(hist[-1]["taken_at"])
        prev = datetime.fromisoformat(hist[-2]["taken_at"]) if len(hist) > 1 else None
        if t.time() >= time(11) and (prev is None or prev.time() < time(11)):
            return side(hist[-1]) if callable(side) else side
        return None
    return decide


SPEC = fw.ForwardSpec(registered_on=date(2026, 10, 5), tests_in_family=66, min_sessions=10, min_trades=8)


def test_the_contract_is_the_one_the_live_intraday_rules_buy():
    exp = [date(2026, 10, 6), date(2026, 10, 13)]
    for side, spot, day in ((1, 22624.0, date(2026, 10, 1)), (-1, 22626.0, date(2026, 10, 6)),
                            (1, 22600.0, date(2026, 10, 13)), (-1, 22575.0, date(2026, 10, 2))):
        assert fw.contract(side, spot, day, exp) == live.contract(side, spot, day, exp)


def test_bought_at_the_next_snapshots_ask_and_sold_at_the_bid_with_costs_but_no_assumed_slippage():
    day = days(1)[0]
    rows = session(day, lambda m: 22500.0 if m <= 11 * 60 else 22540.0)
    [t] = fw.run_rule(fw.Rule("x", at_eleven(1)), {day: rows}, SPEC)
    assert t["signal_at"] == f"{day}T11:00:10" and t["contract"] == {"expiry": FAR, "strike": 22500,
                                                                     "option_type": "CE"}
    # the 11:00 snapshot the rule read is not traded on: the 11:05 one is (spot 22,540 by then)
    assert t["entry_at"] == f"{day}T11:05:10" and t["ask_in"] == 100 + 20 + 0.25
    assert t["exit_at"] == f"{day}T15:25:10" and t["bid_out"] == 100 + 20 - 0.25
    assert fw.COSTS.premium_slippage_pct == 0
    cost = fw.COSTS.cost_pct(120.25, 119.75, day, day, 65)
    assert t["counted"] and t["cost_pct"] == round(cost, 3)
    assert t["net_pct"] == round((119.75 / 120.25 - 1) * 100 - cost, 3)
    assert 0.5 < cost < 1.5                       # brokerage, STT and charges on a lot at ~Rs 120


def test_a_leg_priced_too_late_is_not_counted():
    day = days(1)[0]
    rows = session(day, flat, drop=("11:05", "11:10", "11:15"))
    [t] = fw.run_rule(fw.Rule("x", at_eleven(1)), {day: rows}, SPEC)
    assert not t["counted"] and t["ask_in"] is None and "net_pct" not in t
    ok = fw.run_rule(fw.Rule("x", at_eleven(1)), {day: rows}, replace(SPEC, max_late_s=1200))
    assert ok[0]["counted"] and ok[0]["entry_at"] == f"{day}T11:20:10"


def test_a_hold_in_minutes_ends_the_trade_before_the_clock_exit():
    day = days(1)[0]
    [t] = fw.run_rule(fw.Rule("x", at_eleven(-1), hold_minutes=30), {day: session(day, flat)}, SPEC)
    assert t["exit_target"] == f"{day}T11:30:10" and t["exit_at"] == f"{day}T11:30:10"
    assert t["contract"]["option_type"] == "PE"


def test_the_rule_sees_only_snapshots_and_bars_that_existed_when_it_decided():
    day = days(1)[0]
    stamps = pd.date_range(f"{day} 09:15", f"{day} 15:25", freq="5min")
    bars = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=stamps)
    seen = []

    def decide(hist, b):
        t = datetime.fromisoformat(hist[-1]["taken_at"])
        assert all(datetime.fromisoformat(h["taken_at"]) <= t for h in hist)
        assert b.empty or b.index.max() + timedelta(minutes=5) <= t
        seen.append(t)
        return 1 if t.time() >= time(13) else None

    trades = fw.run_rule(fw.Rule("x", decide), {day: session(day, flat)}, SPEC, bars)
    assert seen[0].time() == time(9, 45, 10) and seen[-1].time() == time(13, 0, 10)   # from first_check, stops
    assert len(trades) == 1                                                              # one trade a session


def test_sessions_before_the_registration_never_count():
    ds = days(3, "2026-10-01")
    rows = {d: session(d, flat) for d in ds}
    spec = replace(SPEC, registered_on=ds[1])
    assert [t["day"] for t in fw.run_rule(fw.Rule("x", at_eleven(1)), rows, spec)] == [d.isoformat() for d in ds[1:]]


def test_features_can_be_read_off_the_nearest_expiry_on_its_expiry_day():
    day = date(2026, 10, 6)
    rows = session(day, flat, expiry="2026-10-06", over=lambda m: {(22500, "PE"): {"oi": 5000}}) + session(day, flat)
    side = {"traded": None, "nearest": None}

    def rule(on):
        def decide(hist, _b):
            side[on] = hist[-1]["put_oi_near"]
            return 1
        return fw.Rule(on, decide, features_on=on)

    for on in side:
        [t] = fw.run_rule(rule(on), {day: rows}, SPEC)
        assert t["contract"]["expiry"] == FAR                  # always the contract that does not expire today
    assert side["nearest"] - side["traded"] == 4000


def test_the_baseline_is_the_same_option_at_the_same_times_every_session():
    ds = days(4)
    moves = {ds[0]: 40, ds[1]: -40, ds[2]: 0, ds[3]: 20}
    rows = {d: session(d, lambda m, d=d: 22500.0 + (moves[d] if m > 11 * 60 + 5 else 0)) for d in ds}
    trades = fw.run_rule(fw.Rule("x", at_eleven(lambda f: 1 if f["spot"] >= 22500 else -1)), rows, SPEC)
    base = fw.baseline(trades, rows, SPEC)
    assert list(base) == [(time(11, 0, 10), time(15, 25), 1)]
    [vals] = base.values()
    assert len(vals) == 4 and vals[0] == trades[0]["net_pct"]            # the trade's own session agrees
    assert all(t["side"] == 1 for t in trades) and vals[0] > vals[3] > vals[2] > vals[1]   # the call, as the index went


def test_with_one_template_the_t_is_welchs():
    rng = random.Random(3)
    trades = [rng.gauss(2, 10) for _ in range(30)]
    base = [rng.gauss(0, 10) for _ in range(90)]
    tpl = (time(11), time(15, 25), 1)
    assert fw.forward_t(trades, {tpl: base}, {tpl: 30})["t"] == welch_t_stat(trades, base)


def test_several_templates_count_each_session_once():
    up, down = (time(11), time(15, 25), 1), (time(11), time(15, 25), -1)
    base = {up: [1.0, 3.0, 5.0], down: [-2.0, 0.0, 2.0]}
    out = fw.forward_t([4.0, 6.0, 5.0, 7.0], base, {up: 3, down: 1})
    assert out["baseline_mean_pct"] == round(0.75 * 3.0 + 0.25 * 0.0, 3) and out["baseline_n"] == 6
    se = (pd.Series([4.0, 6, 5, 7]).var() / 4 + 0.75 ** 2 * 4 / 3 + 0.25 ** 2 * 4 / 3) ** 0.5
    assert out["t"] == round((5.5 - 2.25) / se, 2)
    assert fw.forward_t([1.0, 2.0], {up: [1.0, 2.0]}, {up: 1, down: 1})["t"] is None   # a template with no baseline


def informed(n: int, seed: int) -> dict:
    """Sessions whose index moves 40-80 points after 11:00, either way, with
    the put OI at the money planted at 10:30 to say which: a rule that reads
    it always wins, by construction."""
    rng = random.Random(seed)
    out = {}
    for d in days(n):
        way, size = rng.choice((1, -1)), rng.uniform(40, 80)
        out[d] = session(d, lambda m, w=way, s=size: 22500.0 + (w * s * min(1, (m - 660) / 60) if m > 660 else 0),
                         over=lambda m, w=way: {(22500, "PE"): {"oi": 1000 + 500 * w}} if m >= 630 else None)
    return out


def reads_the_plant(f):
    return 1 if f["oi_flow_open"] > 0 else -1


def test_no_verdict_until_the_minimums_are_met():
    rows = informed(9, seed=1)
    trades = fw.run_rule(fw.Rule("x", at_eleven(reads_the_plant)), rows, SPEC)
    out = fw.judge(trades, rows, SPEC)
    assert out["status"] == "waiting" and "verdict" not in out
    assert out["reason"] == "Not judged: 9 of 10 sessions and 9 of 8 counted trades since 2026-10-05."


def test_a_rule_that_knows_the_move_is_approved_and_its_opposite_is_rejected():
    rows = informed(30, seed=2)
    spec = replace(SPEC, min_sessions=30, min_trades=30)        # 10 trades need t >= 4.49 at 66 tests
    good = fw.judge(fw.run_rule(fw.Rule("x", at_eleven(reads_the_plant)), rows, spec), rows, spec)
    assert good["status"] == "judged" and good["verdict"] == "APPROVED", good["reason"]
    assert good["mean_pct"] > 10 and good["t"] > good["required_t"]
    bad = fw.judge(fw.run_rule(fw.Rule("x", at_eleven(lambda f: -reads_the_plant(f))), rows, spec), rows, spec)
    assert bad["verdict"] == "REJECTED" and bad["reason"].startswith("Lost money")


def test_the_sample_closes_when_the_minimums_are_first_met_so_waiting_longer_changes_nothing():
    rows = informed(16, seed=4)
    ds = sorted(rows)
    rule = fw.Rule("x", at_eleven(reads_the_plant))
    early = {d: rows[d] for d in ds[:11]}
    a = fw.judge(fw.run_rule(rule, early, SPEC), early, SPEC)
    b = fw.judge(fw.run_rule(rule, rows, SPEC), rows, SPEC)
    assert a["closed_on"] == b["closed_on"] == ds[9].isoformat()           # the tenth session
    for k in ("num_trades", "mean_pct", "t", "baseline_mean_pct", "required_t", "verdict"):
        assert a[k] == b[k], k
    assert b["counted_trades"] == 16 and b["num_trades"] == 10


def test_the_bar_is_the_registrations_family_count_at_the_samples_own_df():
    from stats.multiple_comparisons import required_t
    rows = informed(12, seed=5)
    out = fw.judge(fw.run_rule(fw.Rule("x", at_eleven(reads_the_plant)), rows, SPEC), rows, SPEC)
    assert out["required_t"] == required_t(66, df=out["num_trades"] - 1)


def test_evaluate_reads_a_snapshot_database_end_to_end(tmp_path):
    path = tmp_path / "snapshots.db"
    rows = informed(10, seed=6)
    option_snapshots_db.save([r for d in sorted(rows) for r in rows[d]], path)
    out = fw.evaluate(fw.Rule("x", at_eleven(reads_the_plant)), SPEC, db_path=path, bars=pd.DataFrame())
    assert out["status"] == "judged" and len(out["trades"]) == 10 and out["mean_pct"] > 10


@pytest.mark.parametrize("edge", [3.0, 5.0, 10.0])
def test_trades_needed_is_the_smallest_sample_that_reaches_the_bar(edge):
    from stats.multiple_comparisons import required_t
    n = fw.trades_needed(edge, 46.0, tests=66)
    se = lambda k: (2 * 46.0 ** 2 / k) ** 0.5          # noqa: E731 — every session a trade, one template
    assert edge / se(n) >= required_t(66, df=n - 1)
    if n <= 200:
        assert edge / se(n - 1) < required_t(66, df=n - 2)
    assert fw.trades_needed(edge * 2, 46.0, tests=66) < n
    assert fw.trades_needed(0.0, 46.0, tests=66, cap=5000) is None
