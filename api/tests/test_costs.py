import pytest
from backtest.costs import CostModel
from backtest.options_engine import OptionsCostModel


def test_index_round_trip_cost_is_positive_and_small():
    cost = CostModel().round_trip_cost_pct()
    assert cost > 0
    # A sanity band, not a precise assertion -- catches a decimal-point
    # or unit error (e.g. accidentally returning a fraction instead of a
    # percentage) without being brittle to a deliberate rate-card tweak.
    assert 0.05 < cost < 2.0


def test_options_round_trip_cost_exceeds_index_cost():
    """Options costs scale with premium, not notional, and premium is a
    small fraction of the underlying -- so proportionally, option costs
    must come out higher than index costs. If this ever inverts, the cost
    model has a unit bug."""
    index_cost = CostModel().round_trip_cost_pct()
    options_cost = OptionsCostModel().round_trip_cost_fraction() * 100
    assert options_cost > index_cost


def test_zero_slippage_model_is_cheaper_than_default():
    default = OptionsCostModel()
    zero_slippage = OptionsCostModel(premium_slippage_pct=0.0)
    assert zero_slippage.round_trip_cost_fraction() < default.round_trip_cost_fraction()


# --- each leg on its own premium (decided 2026-09-24) -------------------------

def test_the_sale_is_charged_on_what_it_sold_for():
    """The sell side — STT, slippage, fees — used to be charged on the entry
    premium, so a trade that tripled paid a third of its real exit costs:
    3.3% where ~7% was due. Winners were flattered; worthless expiries were
    over-charged. Each leg is now charged on its own premium."""
    m = OptionsCostModel()
    flat, winner, loser = m.cost_pct(100, 100), m.cost_pct(100, 336), m.cost_pct(100, 0)
    assert flat == pytest.approx(m.round_trip_cost_fraction() * 100)      # a flat trade: unchanged
    assert winner == pytest.approx((m.buy_fraction() + 3.36 * m.sell_fraction()) * 100)
    assert winner > 7.0 and loser == pytest.approx(m.buy_fraction() * 100)
    assert m.buy_fraction() + m.sell_fraction() == pytest.approx(m.round_trip_cost_fraction())


def test_the_backtest_charges_each_leg_on_its_own_premium(tmp_path):
    import sqlite3

    import pandas as pd

    from backtest.options_engine import run_options_backtest
    db = tmp_path / "o.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, "
              "open REAL, high REAL, low REAL, close REAL, settle_price REAL, open_interest REAL, volume REAL)")
    c.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        ("2026-01-02", "2026-02-26", 23000.0, "CE", 0, 0, 0, 100.0, 0, 5000, 1),
        ("2026-01-05", "2026-02-26", 23000.0, "CE", 0, 0, 0, 300.0, 0, 5000, 1)])
    c.commit(); c.close()
    days = ["2026-01-01", "2026-01-02", "2026-01-05"]
    trades = run_options_backtest(["2026-01-01"], pd.Series(23000.0, index=days), days, hold_days=1,
                                  min_days_to_expiry=7, db_path=db)
    assert len(trades) == 1
    t = trades[0]
    assert t.cost_pct == pytest.approx(round(OptionsCostModel().cost_pct(100, 300), 3))
    assert t.net_return_pct == pytest.approx(round(200.0 - t.cost_pct, 2))
