"""The real spread Phase 1 is re-run with. What must hold: the half-spread is
(ask - bid) / 2 on two-sided quotes only; contracts are chosen as Phase 1's
pick() chooses them (nearest expiry after the day, the monthly at least 14
days out, the strike nearest the moneyness target); the close window is
14:30-15:30; and the cost model charges the half-spread in points each side."""

from datetime import date

import pytest

import backtest.spread_model as sm
from backtest.options_engine import OptionsCostModel
from storage import option_snapshots_db as snapdb


def test_nearest_is_after_the_day_and_monthly_the_last_of_its_month_14_days_out():
    got = sm.classify_expiries("2026-10-06", ["2026-10-06", "2026-10-13", "2026-10-27"])
    assert got == {"nearest": "2026-10-13", "monthly": "2026-10-27"}       # never the one expiring that day
    late = sm.classify_expiries("2026-10-20", ["2026-10-20", "2026-10-27", "2026-11-03"])
    assert late == {"nearest": "2026-10-27"}       # Oct's monthly 7 days out; 3 Nov is not known to be Nov's last
    full = sm.classify_expiries("2026-10-20", ["2026-10-27", "2026-11-03", "2026-11-24", "2026-12-29"])
    assert full["monthly"] == "2026-11-24"         # a later month recorded shows November is complete
    assert sm.classify_expiries("2026-10-01", []) == {}


def test_the_strike_nearest_the_target_ties_to_the_lower():
    quotes = {22500.0: (1, 2), 22550.0: (1, 2), 22600.0: (1, 2)}
    assert sm.nearest_strike(quotes, 22525.0) == 22500.0
    assert sm.nearest_strike(quotes, 22590.0) == 22600.0
    assert sm.nearest_strike({}, 1.0) is None


def _row(taken_at, expiry, strike, kind, spot, bid, ask):
    return {"taken_at": taken_at, "expiry": expiry, "strike": strike, "option_type": kind, "spot": spot,
            "ltp": None, "bid": bid, "ask": ask, "bid_qty": 50, "ask_qty": 50, "iv": 12.0, "oi": 1000, "volume": 10}


@pytest.fixture
def db(tmp_path):
    """One made-up session, spot 22,500 throughout: the weekly quoted 1 point
    wide at 10:00 and 3 wide at 15:00, the monthly 2 and 6. Strikes 22,275 /
    22,500 / 22,725 are the 1% targets. A one-sided and a crossed quote must be
    ignored, and the middle expiry (13 Oct) is neither choice."""
    path = tmp_path / "snap.db"
    rows = []
    for t, w_week, w_month in (("2026-10-01T10:00:00", 1.0, 2.0), ("2026-10-01T15:00:00", 3.0, 6.0)):
        for expiry, width in (("2026-10-06", w_week), ("2026-10-27", w_month), ("2026-10-13", 50.0)):
            for k in (22275.0, 22500.0, 22725.0):
                for kind in ("CE", "PE"):
                    otm = (k > 22500) == (kind == "CE")
                    mid = 100.0 if k == 22500.0 else (50.0 if otm else 250.0)
                    rows.append(_row(t, expiry, k, kind, 22500.0, mid - width / 2, mid + width / 2))
            rows.append(_row(t, expiry, 22300.0, "CE", 22500.0, 0.0, 300.0))       # no bid: ignored
            rows.append(_row(t, expiry, 22700.0, "PE", 22500.0, 260.0, 240.0))     # crossed: ignored
    snapdb.save(rows, path)
    return path


def test_half_spreads_in_points_and_percent_by_bucket(db):
    m = sm.measure_spreads(db)
    assert m["sessions"] == ["2026-10-01"] and m["close_sessions"] == ["2026-10-01"] and m["window"] == "14:30-15:30"
    b = {(x["expiry"], x["moneyness"]): x for x in m["buckets"]}
    assert set(b) == {(e, lb) for e in ("nearest", "monthly") for lb in ("1% OTM", "ATM", "1% ITM")}
    atm = b[("nearest", "ATM")]
    assert atm["half_spread_pts"] == 1.5 and atm["n"] == 2                  # 15:00 only: one call, one put
    assert atm["half_spread_pct"] == 1.5                                    # 1.5 on a mid of 100
    assert atm["all_day_half_spread_pts"] == 1.0 and atm["all_day_n"] == 4  # median of 0.5, 0.5, 1.5, 1.5
    assert b[("monthly", "ATM")]["half_spread_pts"] == 3.0
    otm = b[("nearest", "1% OTM")]
    assert otm["half_spread_pts"] == 1.5 and otm["half_spread_pct"] == 3.0  # the cheap side: a mid of 50
    assert b[("monthly", "1% ITM")]["half_spread_pct"] == pytest.approx(1.2)  # 3 on a mid of 250
    assert sm.half_spreads(m)[("monthly", "1% OTM")] == 3.0
    assert sm.half_spreads(m, "all_day")[("nearest", "ATM")] == 1.0


def test_a_session_with_no_close_snapshots_has_no_close_measure(tmp_path):
    path = tmp_path / "snap.db"
    snapdb.save([_row("2026-10-01T09:30:00", e, 22500.0, k, 22500.0, 99.0, 101.0)
                 for e in ("2026-10-06", "2026-10-27") for k in ("CE", "PE")], path)
    m = sm.measure_spreads(path)
    assert m["close_sessions"] == [] and sm.half_spreads(m) is None
    assert sm.half_spreads(m, "all_day")[("monthly", "ATM")] == 1.0


def test_the_close_window_is_1430_to_1530():
    assert sm.in_close_window("2026-10-01T14:30:00") and sm.in_close_window("2026-10-01T15:30:59")
    assert not sm.in_close_window("2026-10-01T14:29:59") and not sm.in_close_window("2026-10-01T15:31:00")


def test_the_spread_cost_model_charges_half_spread_points_each_side():
    on = date(2023, 6, 1)
    base = OptionsCostModel(premium_slippage_pct=0.0)
    model = sm.SpreadCostModel(half_spread_pts=2.0)
    assert model.premium_slippage_pct == 0.0
    assert model.buy_cost_rs(100.0, 65, on) == pytest.approx(base.buy_cost_rs(100.0, 65, on) + 130.0)
    assert model.sell_cost_rs(100.0, 65, on) == pytest.approx(base.sell_cost_rs(100.0, 65, on) + 130.0)
    # Points, not percent: the same 2 points on a premium ten times larger.
    assert model.buy_cost_rs(1000.0, 65, on) - base.buy_cost_rs(1000.0, 65, on) == pytest.approx(130.0)
    # A sale that would cost more than it fetches lapses: never more than the sale value.
    assert model.sell_cost_rs(1.0, 65, on) == 65.0
    assert model.cost_pct(100.0, 100.0, on, on) == pytest.approx(base.cost_pct(100.0, 100.0, on, on) + 4.0)
    assert "half-spread of 2 points" in model.summary(on) and "slippage" not in model.summary(on)
    assert sm.SpreadCostModel().buy_cost_rs(100.0, 65, on) == pytest.approx(base.buy_cost_rs(100.0, 65, on))
