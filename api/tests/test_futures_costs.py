"""The index engine's futures costs: a discount broker's rate card and the
statutory rates in force on each leg's own date (since 2026-09-27).

The model used to charge 0.03% of notional as brokerage, where Zerodha's is
"0.03% or Rs 20 an order, whichever is lower" — Rs 20, or 0.0012%, on a NIFTY
lot of ~Rs 16 lakh — and a flat 0.02% STT on the sale, which was the rate only
from October 2024 to March 2026. Every dated rate below is from the exchange
circular that announced it.
"""

from datetime import date

import pandas as pd
import pytest

from backtest.costs import LOT_SIZE, CostModel
from backtest.engine import run_backtest

TODAY = "2026-09-25"  # a session under the current rate card


# --- the rate card, by date ----------------------------------------------------

@pytest.mark.parametrize("day,rate", [
    ("2006-06-01", 0.00017),   # the rate the Finance Act 2013 cut from
    ("2013-05-31", 0.00017),
    ("2013-06-01", 0.0001),    # Finance Act 2013
    ("2023-03-31", 0.0001),
    ("2023-04-01", 0.000125),  # Finance Act 2023 — NSE/FATAX/56235
    ("2024-09-30", 0.000125),
    ("2024-10-01", 0.0002),    # Finance (No. 2) Act 2024 — NSE/FATAX/63809
    ("2026-03-31", 0.0002),
    ("2026-04-01", 0.0005),    # Finance Act 2026 — NSE/FATAX/73524
    ("2026-09-27", 0.0005),
])
def test_stt_on_a_futures_sale_is_the_rate_in_force_that_day(day, rate):
    assert CostModel().stt_sell_rate(day) == rate


@pytest.mark.parametrize("day,rate", [
    ("2024-09-30", 0.000019),   # the slab card brokers passed on, ~Rs 190 a crore
    ("2024-10-01", 0.0000183),  # one rate for all (NSE/FA/64232): Rs 173 + Rs 10 IPFT a crore
    ("2026-03-01", 0.0000183),  # IPFT folded into one Rs 183 charge, same total (NSE/FA/73061)
])
def test_the_exchange_charge_on_futures_is_the_rate_in_force_that_day(day, rate):
    assert CostModel().exchange_rate(day) == rate


def test_a_date_before_any_verified_rate_is_refused_not_guessed():
    with pytest.raises(ValueError, match="2006-06-01"):
        CostModel().stt_sell_rate("2006-05-31")


def test_dates_and_timestamps_are_read_the_same_way():
    m = CostModel()
    assert m.stt_sell_rate(date(2026, 4, 1)) == m.stt_sell_rate(pd.Timestamp("2026-04-01")) == 0.0005
    assert m.stt_sell_rate(pd.Timestamp("2026-03-31 15:29", tz="Asia/Kolkata")) == 0.0002


def test_brokerage_is_three_basis_points_or_20_rupees_whichever_is_lower():
    m = CostModel()
    assert m.brokerage_rs(25_000 * LOT_SIZE) == 20.0            # a NIFTY lot: always the cap
    assert m.brokerage_rs(25_000) == pytest.approx(7.5)          # one unit: 0.03%
    assert m.brokerage_rs(20 / 0.0003) == pytest.approx(20.0)    # where the two meet


def test_one_nifty_lot_at_25000_costs_about_966_rupees_before_slippage():
    """Rs 20 an order plus GST, exchange and SEBI charges both ways, stamp duty
    on the buy and 0.05% STT on the sale. The old rates came to about Rs 1,581
    on the same lot, most of it a 0.03% brokerage no discount broker charges
    on a futures lot."""
    m = CostModel(slippage_pct=0.0)
    value = 25_000 * LOT_SIZE
    fees = (20 + value * (0.0000183 + 0.000001)) * 1.18   # brokerage, exchange, SEBI, GST — each leg
    by_hand = 2 * fees + value * 0.00002 + value * 0.0005
    total = m.buy_cost_rs(25_000, LOT_SIZE, TODAY) + m.sell_cost_rs(25_000, LOT_SIZE, TODAY)
    assert total == pytest.approx(by_hand)
    assert total == pytest.approx(966.22, abs=0.01)
    assert m.round_trip_cost_pct(25_000, TODAY) == pytest.approx(by_hand / value * 100)


def test_the_sale_pays_the_stt_in_force_on_the_day_it_is_sold():
    m = CostModel()
    before, after = m.sell_cost_rs(25_000, LOT_SIZE, "2026-03-31"), m.sell_cost_rs(25_000, LOT_SIZE, "2026-04-01")
    assert after - before == pytest.approx(25_000 * LOT_SIZE * 0.0003)
    straddling = m.cost_pct(25_000, 25_000, "2026-03-30", "2026-04-01")
    assert straddling == pytest.approx(
        (m.buy_cost_rs(25_000, LOT_SIZE, "2026-03-30") + after) / (25_000 * LOT_SIZE) * 100)


def test_the_cost_is_a_share_of_the_notional_at_entry():
    """So it subtracts straight from the engine's gross return, which is a %
    of the entry price too."""
    m = CostModel()
    rs = m.buy_cost_rs(20_000, LOT_SIZE, TODAY) + m.sell_cost_rs(22_000, LOT_SIZE, TODAY)
    assert m.cost_pct(20_000, 22_000, TODAY, TODAY) == pytest.approx(rs / (20_000 * LOT_SIZE) * 100)


def test_a_short_sells_at_entry_and_buys_at_exit():
    """STT is charged on the sale and stamp duty on the purchase. A short's
    sale is its entry, so it pays STT on the entry price at the entry day's
    rate. The old model charged every trade as if it were long."""
    m = CostModel()
    short = m.cost_pct(25_000, 24_000, "2026-03-31", "2026-04-01", direction="short")
    legs = m.sell_cost_rs(25_000, LOT_SIZE, "2026-03-31") + m.buy_cost_rs(24_000, LOT_SIZE, "2026-04-01")
    assert short == pytest.approx(legs / (25_000 * LOT_SIZE) * 100)
    # Its sale fell under the 0.02% STT; the long's, a day later, under 0.05%.
    assert short < m.cost_pct(25_000, 24_000, "2026-03-31", "2026-04-01", direction="long")


def test_an_unknown_direction_is_refused():
    with pytest.raises(ValueError, match="sideways"):
        CostModel().cost_pct(25_000, 25_000, TODAY, TODAY, direction="sideways")


def test_rates_can_be_pinned_to_one_day_to_ask_what_history_would_cost_now():
    now = CostModel(rates_as_of="2026-09-27")
    assert now.cost_pct(5_000, 5_000, "2010-01-04", "2010-01-18") == pytest.approx(
        CostModel().cost_pct(5_000, 5_000, "2026-09-27", "2026-09-27"))


def test_the_lot_is_the_nifty_lot_the_option_research_uses():
    from backtest import pattern_options
    assert LOT_SIZE == pattern_options.LOT_SIZE


# --- the engine charges each trade on its own prices and dates ------------------

def _flat_bars(days: list[str], prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"open": prices, "high": prices, "low": prices, "close": prices},
                        index=pd.DatetimeIndex(days))


def _two_trades(direction: str):
    """One 2-session trade sold before the Finance Act 2026, one after."""
    df = _flat_bars(["2026-03-26", "2026-03-27", "2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02"],
                    [22_000.0, 22_100.0, 22_200.0, 22_300.0, 22_400.0, 22_500.0])
    signal = pd.Series(False, index=df.index)
    signal.iloc[0] = signal.iloc[3] = True
    trades = run_backtest(df, signal, pd.Series("N/A", index=df.index), direction=direction,
                          hold_days=2, cost_model=CostModel())
    assert [(t.entry_date, t.exit_date) for t in trades] == [("2026-03-27", "2026-03-30"),
                                                             ("2026-04-01", "2026-04-02")]
    return trades


def test_the_engine_charges_each_trade_at_its_own_prices_and_dates():
    m = CostModel()
    before, after = _two_trades("long")
    assert before.cost_pct == pytest.approx(round(m.cost_pct(22_100, 22_200, "2026-03-27", "2026-03-30"), 3))
    assert after.cost_pct == pytest.approx(round(m.cost_pct(22_400, 22_500, "2026-04-01", "2026-04-02"), 3))
    assert after.cost_pct > before.cost_pct + 0.02   # 0.05% STT on the sale, not 0.02%
    for t in (before, after):
        assert t.net_return_pct == pytest.approx(t.gross_return_pct - t.cost_pct, abs=0.002)


def test_the_engine_charges_a_short_as_a_sale_then_a_purchase():
    m = CostModel()
    _, after = _two_trades("short")
    assert after.cost_pct == pytest.approx(
        round(m.cost_pct(22_400, 22_500, "2026-04-01", "2026-04-02", direction="short"), 3))
