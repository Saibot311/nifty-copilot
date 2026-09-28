import pytest
from backtest.costs import CostModel
from backtest.options_engine import LOT_SIZE, OptionsCostModel

TODAY = "2026-09-25"  # a session under the current rate card


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
    options_cost = OptionsCostModel().round_trip_cost_fraction(100, TODAY) * 100
    assert options_cost > index_cost


def test_zero_slippage_model_is_cheaper_than_default():
    default = OptionsCostModel()
    zero_slippage = OptionsCostModel(premium_slippage_pct=0.0)
    assert zero_slippage.round_trip_cost_fraction(100, TODAY) < default.round_trip_cost_fraction(100, TODAY)


# --- each leg on its own premium (decided 2026-09-24) -------------------------

def test_the_sale_is_charged_on_what_it_sold_for():
    """The sell side — STT, slippage, fees — used to be charged on the entry
    premium, so a trade that tripled paid a third of its real exit costs:
    3.3% where ~7% was due. Winners were flattered; worthless expiries were
    over-charged. Each leg is now charged on its own premium."""
    m = OptionsCostModel()
    paid = 100 * LOT_SIZE
    flat, winner, loser = (m.cost_pct(100, 100, TODAY, TODAY), m.cost_pct(100, 336, TODAY, TODAY),
                           m.cost_pct(100, 0, TODAY, TODAY))
    assert flat == pytest.approx(m.round_trip_cost_fraction(100, TODAY) * 100)      # a flat trade: both legs at 100
    assert winner == pytest.approx((m.buy_cost_rs(100, LOT_SIZE, TODAY) + m.sell_cost_rs(336, LOT_SIZE, TODAY))
                                   / paid * 100)
    assert winner > 7.0 and loser == pytest.approx(m.buy_cost_rs(100, LOT_SIZE, TODAY) / paid * 100)


def test_the_backtest_charges_each_leg_on_its_own_premium(tmp_path):
    t = _one_backtest_trade(tmp_path, "2026-01-02", "2026-01-05", 100.0, 300.0)
    assert t.cost_pct == pytest.approx(round(OptionsCostModel().cost_pct(100, 300, "2026-01-02", "2026-01-05"), 3))
    assert t.net_return_pct == pytest.approx(round(200.0 - t.cost_pct, 2))


# --- the rate card, by date (2026-09-27) ---------------------------------------
# The model used to charge 0.10% STT, 0.05% exchange and 0.03% "brokerage" on
# premium: about Rs 19 a lot at a Rs 100 premium, before slippage, where the
# published rates come to about Rs 63. Every rate below is from the exchange
# circular that announced it.

@pytest.mark.parametrize("day,rate", [
    ("2014-10-01", 0.00017),   # in force per NSE/FATAX/27711 (Finance (No. 2) Act 2014 table)
    ("2016-05-31", 0.00017),
    ("2016-06-01", 0.0005),    # Finance Act 2016 — NSE/FATAX/32385
    ("2023-03-31", 0.0005),
    ("2023-04-01", 0.000625),  # Finance Act 2023 — NSE/FATAX/56235
    ("2024-09-30", 0.000625),
    ("2024-10-01", 0.001),     # Finance (No. 2) Act 2024 — NSE/FATAX/63809
    ("2026-03-31", 0.001),
    ("2026-04-01", 0.0015),    # Finance Act 2026 — NSE/FATAX/73524
    ("2026-09-27", 0.0015),
])
def test_stt_on_an_option_sale_is_the_rate_in_force_that_day(day, rate):
    assert OptionsCostModel().stt_sell_rate(day) == rate


@pytest.mark.parametrize("day,rate", [
    ("2024-09-30", 0.0005),     # the slab card brokers passed on, ~Rs 50 a lakh of premium
    ("2024-10-01", 0.0003553),  # one rate for all (NSE/FA/64232): Rs 3,503 + Rs 50 IPFT a crore
    ("2026-03-01", 0.0003553),  # IPFT folded into the charge, same total (NSE/FA/73061)
])
def test_the_exchange_charge_is_the_rate_in_force_that_day(day, rate):
    assert OptionsCostModel().exchange_rate(day) == rate


def test_dates_and_timestamps_are_read_the_same_way():
    from datetime import date

    import pandas as pd
    m = OptionsCostModel()
    assert m.stt_sell_rate(date(2026, 4, 1)) == m.stt_sell_rate(pd.Timestamp("2026-04-01 09:15", tz="Asia/Kolkata"))
    assert m.stt_sell_rate(date(2026, 3, 31)) == 0.001


def test_a_date_before_any_verified_rate_is_refused_not_guessed():
    with pytest.raises(ValueError, match="2014-10-01"):
        OptionsCostModel().stt_sell_rate("2014-09-30")


def test_one_lot_at_a_100_premium_costs_about_63_rupees_before_slippage():
    """The figure the old model got wrong by 3x: Rs 20 an order plus GST, STT
    on the sale, exchange and SEBI charges both ways, stamp duty on the buy."""
    m = OptionsCostModel(premium_slippage_pct=0.0)
    ticket = 100 * LOT_SIZE
    fees = 20 + ticket * (0.0003553 + 0.000001)          # brokerage, exchange, SEBI — each leg
    by_hand = 2 * fees * 1.18 + ticket * 0.00003 + ticket * 0.0015
    total = m.buy_cost_rs(100, LOT_SIZE, TODAY) + m.sell_cost_rs(100, LOT_SIZE, TODAY)
    assert total == pytest.approx(by_hand)
    assert total == pytest.approx(62.61, abs=0.01)


def test_brokerage_is_a_flat_20_rupees_an_order_whatever_the_premium():
    m = OptionsCostModel(premium_slippage_pct=0.0)
    cheap, dear = m.buy_cost_rs(10, LOT_SIZE, TODAY), m.buy_cost_rs(500, LOT_SIZE, TODAY)
    per_rupee = 0.0003553 + 0.000001 + 0.00003 + 0.18 * (0.0003553 + 0.000001)
    assert cheap == pytest.approx(20 * 1.18 + 10 * LOT_SIZE * per_rupee)
    assert dear == pytest.approx(20 * 1.18 + 500 * LOT_SIZE * per_rupee)
    # As a share of what was paid it is the cheap option that suffers.
    assert cheap / (10 * LOT_SIZE) > 10 * dear / (500 * LOT_SIZE)


def test_more_lots_in_one_order_share_one_brokerage():
    m = OptionsCostModel()
    one, ten = m.buy_cost_rs(50, LOT_SIZE, TODAY), m.buy_cost_rs(50, 10 * LOT_SIZE, TODAY)
    assert ten == pytest.approx(10 * one - 9 * 20 * 1.18)
    assert m.cost_pct(50, 50, TODAY, TODAY, quantity=10 * LOT_SIZE) < m.cost_pct(50, 50, TODAY, TODAY)


def test_the_sale_pays_the_stt_in_force_on_the_day_it_is_sold():
    m = OptionsCostModel()
    before, after = m.sell_cost_rs(300, LOT_SIZE, "2026-03-31"), m.sell_cost_rs(300, LOT_SIZE, "2026-04-01")
    assert after - before == pytest.approx(300 * LOT_SIZE * 0.0005)
    straddling = m.cost_pct(100, 300, "2026-03-30", "2026-04-01")
    assert straddling == pytest.approx((m.buy_cost_rs(100, LOT_SIZE, "2026-03-30") + after) / (100 * LOT_SIZE) * 100)


def test_a_sale_that_would_cost_more_than_it_fetches_is_not_made():
    """With a flat Rs 20 an order, selling a lot for Rs 6.50 would lose money
    on the sale itself. A buyer lets that option lapse instead: no order, no
    charges, nothing received — so a loss never exceeds what was paid plus
    the buy's costs."""
    m = OptionsCostModel()
    assert m.sell_cost_rs(0.0, LOT_SIZE, TODAY) == 0.0
    assert m.sell_cost_rs(0.10, LOT_SIZE, TODAY) == pytest.approx(0.10 * LOT_SIZE)
    worthless = m.cost_pct(10, 0.10, TODAY, TODAY)
    assert (0.10 - 10) / 10 * 100 - worthless == pytest.approx(-100 - m.buy_cost_rs(10, LOT_SIZE, TODAY) / 6.5)


def test_rates_can_be_pinned_to_one_day_to_ask_what_history_would_cost_now():
    now = OptionsCostModel(rates_as_of="2026-09-27")
    assert now.cost_pct(100, 100, "2019-01-02", "2019-01-09") == pytest.approx(
        OptionsCostModel().cost_pct(100, 100, "2026-09-27", "2026-09-27"))


def test_a_backtest_trade_sold_after_the_finance_act_2026_pays_the_new_stt(tmp_path):
    t = _one_backtest_trade(tmp_path, "2026-03-31", "2026-04-01", 100.0, 100.0)
    m = OptionsCostModel()
    assert t.cost_pct == pytest.approx(round(m.cost_pct(100, 100, "2026-03-31", "2026-04-01"), 3))
    assert t.cost_pct > round(m.cost_pct(100, 100, "2026-03-31", "2026-03-31"), 3)


def test_the_backtest_charges_brokerage_on_the_lot_it_is_given(tmp_path):
    t = _one_backtest_trade(tmp_path, "2026-01-02", "2026-01-05", 100.0, 300.0, quantity=20)
    assert t.cost_pct == pytest.approx(round(OptionsCostModel().cost_pct(100, 300, "2026-01-02", "2026-01-05",
                                                                         quantity=20), 3))


def _one_backtest_trade(tmp_path, entry: str, exit_: str, entry_premium: float, exit_premium: float, **kw):
    import sqlite3

    import pandas as pd

    from backtest.options_engine import run_options_backtest
    db = tmp_path / "o.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, "
              "open REAL, high REAL, low REAL, close REAL, settle_price REAL, open_interest REAL, volume REAL)")
    c.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        (entry, "2026-05-26", 23000.0, "CE", 0, 0, 0, entry_premium, 0, 5000, 1),
        (exit_, "2026-05-26", 23000.0, "CE", 0, 0, 0, exit_premium, 0, 5000, 1)])
    c.commit(); c.close()
    days = ["2026-01-01" if entry.startswith("2026-01") else "2026-03-30", entry, exit_]
    trades = run_options_backtest([days[0]], pd.Series(23000.0, index=days), days, hold_days=1,
                                  min_days_to_expiry=7, db_path=db, **kw)
    assert len(trades) == 1
    return trades[0]


def test_the_summary_names_each_rate_in_force_that_day():
    m = OptionsCostModel()
    assert m.summary("2026-09-27") == ("₹20 an order plus 18% GST, 0.15% STT on the sale, 0.0355% exchange "
                                       "charges and 1.5% slippage each way")
    assert "0.1% STT" in m.summary("2025-01-02")
