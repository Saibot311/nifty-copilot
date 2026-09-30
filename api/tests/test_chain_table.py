"""The option chain, contract by contract. What must hold: every strike NSE
lists is a row; a side NSE does not list is absent, not a zero; a buyer pays
the ask; and every rupee in the buyer's view comes from the same rate card as
the backtests — with the real spread in place of the assumed slippage."""

from datetime import date

import pytest
from fastapi import HTTPException

import options.chain_table as ct
from backtest.options_engine import OptionsCostModel

TODAY = date(2026, 9, 28)
EXPIRY = "06-Oct-2026"
SPOT = 22780.25


def _side(strike, ltp=100.0, bid=99.0, ask=101.0, iv=12.5, oi=5000, oi_chg=250, vol=12000, change=-4.5,
          kind="CE"):
    """One contract as NSE's v3 chain sends it."""
    return {"PChange": change, "buyPrice1": bid, "buyQuantity1": 390, "change": change,
            "changeinOpenInterest": oi_chg, "expiryDate": "06-10-2026",
            "identifier": f"OPTIDXNIFTY06-10-2026{kind}{strike:.2f}", "impliedVolatility": iv,
            "lastPrice": ltp, "openInterest": oi, "optionType": None, "pChange": change,
            "pchangeinOpenInterest": 5.0, "sellPrice1": ask, "sellQuantity1": 195, "strikePrice": strike,
            "totalBuyQuantity": 31980, "totalSellQuantity": 56290, "totalTradedVolume": vol,
            "underlying": "NIFTY", "underlyingValue": SPOT}


# NSE lists a strike with one side missing as a dict of zeros, not a missing key.
ABSENT = {"PChange": 0, "buyPrice1": 0, "buyQuantity1": 0, "change": 0, "changeinOpenInterest": 0,
          "expiryDate": None, "identifier": None, "impliedVolatility": 0, "lastPrice": 0, "openInterest": 0,
          "optionType": None, "pChange": 0, "pchangeinOpenInterest": 0, "sellPrice1": 0, "sellQuantity1": 0,
          "strikePrice": 0, "totalBuyQuantity": 0, "totalSellQuantity": 0, "totalTradedVolume": 0,
          "underlying": None, "underlyingValue": 0}


def _payload(rows):
    return {"records": {"data": [{"expiryDates": EXPIRY, "strikePrice": s, "CE": ce, "PE": pe} for s, ce, pe in rows],
                        "timestamp": "28-Sep-2026 15:40:00", "underlyingValue": SPOT,
                        "expiryDates": [EXPIRY], "strikePrices": [r[0] for r in rows]},
            "filtered": {}}


def _table(rows, expiries=(EXPIRY,)):
    return ct.build_chain_table(_payload(rows), EXPIRY, list(expiries), TODAY)


def _row(t, strike):
    return next(r for r in t["rows"] if r["strike"] == strike)


STANDARD = [(s, _side(s, kind="CE"), _side(s, kind="PE")) for s in (22700.0, 22750.0, 22800.0, 22850.0)]


def test_every_strike_nse_lists_is_a_row_in_strike_order():
    shuffled = [STANDARD[2], STANDARD[0], STANDARD[3], STANDARD[1]]
    t = _table(shuffled)
    assert [r["strike"] for r in t["rows"]] == [22700.0, 22750.0, 22800.0, 22850.0]
    assert t["strikes"] == 4 and t["expiry"] == EXPIRY and t["underlying_value"] == SPOT
    assert t["as_of"] == "28-Sep-2026 15:40:00" and t["lot_size"] == 65


def test_every_expiry_nse_lists_is_offered_not_only_the_first_eight():
    expiries = [f"{d:02d}-Oct-2026" for d in range(1, 19)]
    assert _table(STANDARD, expiries)["expiries"] == expiries


def test_the_money_and_days_to_expiry():
    t = _table(STANDARD)
    assert t["atm_strike"] == 22800.0 and _row(t, 22800.0)["is_atm"] and not _row(t, 22750.0)["is_atm"]
    assert t["days_to_expiry"] == 8


def test_a_side_nse_does_not_list_is_absent_not_a_zero_priced_contract():
    t = _table([(22700.0, ABSENT, _side(22700.0, kind="PE"))])
    assert _row(t, 22700.0)["call"] is None
    assert _row(t, 22700.0)["put"]["ltp"] == 100.0


def test_a_contract_carries_what_nse_published_for_it():
    c = _row(_table(STANDARD), 22800.0)["call"]
    assert c["identifier"] == "OPTIDXNIFTY06-10-2026CE22800.00"
    assert (c["ltp"], c["change"], c["bid"], c["ask"], c["bid_qty"], c["ask_qty"]) == (100.0, -4.5, 99.0, 101.0, 390, 195)
    assert (c["iv"], c["oi"], c["oi_change"], c["volume"]) == (12.5, 5000, 250, 12000)


def test_what_nse_reports_as_zero_for_want_of_a_trade_is_shown_as_missing():
    """No trade today is not a price of zero, and no IV is not an IV of zero."""
    c = _row(_table([(22800.0, _side(22800.0, ltp=0, change=0, iv=0), _side(22800.0, kind="PE"))]), 22800.0)["call"]
    assert c["ltp"] is None and c["change"] is None and c["iv"] is None
    assert c["oi"] == 5000  # open interest of zero is a real zero; this one is not zero either


def test_a_buyer_pays_the_ask_for_65_units_and_sees_the_real_spread():
    b = _row(_table(STANDARD), 22800.0)["call"]["buyer"]
    assert b["price"] == 101.0 and b["price_source"] == "ask"
    assert b["lot_rs"] == pytest.approx(101.0 * 65)
    assert b["spread_rs"] == pytest.approx((101.0 - 99.0) * 65)


def test_charges_are_the_backtests_rate_card_with_the_real_spread_instead_of_assumed_slippage():
    b = _row(_table(STANDARD), 22800.0)["call"]["buyer"]
    value = 101.0 * 65
    fees = (20 + value * (0.0003553 + 0.000001)) * 1.18          # brokerage, exchange, SEBI, and GST on them
    assert b["buy_charges_rs"] == pytest.approx(fees + value * 0.00003, abs=0.01)   # + stamp duty
    assert b["sell_charges_rs"] == pytest.approx(fees + value * 0.0015, abs=0.01)   # + STT on the sale
    m = OptionsCostModel(premium_slippage_pct=0.0)
    assert b["buy_charges_rs"] == pytest.approx(m.buy_cost_rs(101.0, 65, TODAY), abs=0.01)
    # The total is the API's, not the browser's (DESIGN.md: no statistic made in JavaScript).
    assert b["charges_rs"] == pytest.approx(b["buy_charges_rs"] + b["sell_charges_rs"], abs=0.01)


def test_without_an_ask_the_last_price_is_used_and_the_view_says_so():
    b = _row(_table([(22800.0, _side(22800.0, ltp=50.0, bid=0, ask=0), _side(22800.0, kind="PE"))]), 22800.0)["call"]["buyer"]
    assert b["price"] == 50.0 and b["price_source"] == "last" and b["spread_rs"] is None


def test_with_no_price_at_all_there_is_no_buyers_view():
    c = _row(_table([(22800.0, _side(22800.0, ltp=0, bid=0, ask=0), _side(22800.0, kind="PE"))]), 22800.0)["call"]
    assert c["buyer"] is None


def test_breakeven_at_expiry_carries_both_legs_charges():
    t = _table(STANDARD)
    call, put = _row(t, 22850.0)["call"]["buyer"], _row(t, 22700.0)["put"]["buyer"]
    per_unit = lambda b: (b["buy_charges_rs"] + b["sell_charges_rs"]) / 65  # noqa: E731
    assert call["breakeven"] == pytest.approx(22850.0 + 101.0 + per_unit(call), abs=0.01)
    assert put["breakeven"] == pytest.approx(22700.0 - 101.0 - per_unit(put), abs=0.01)
    assert call["needs_move_pts"] == pytest.approx(call["breakeven"] - SPOT, abs=0.01) and call["needs_move_pts"] > 0
    assert put["needs_move_pts"] == pytest.approx(put["breakeven"] - SPOT, abs=0.01) and put["needs_move_pts"] < 0
    assert call["needs_move_pct"] == pytest.approx(call["needs_move_pts"] / SPOT * 100, abs=0.01)


def test_moneyness_is_direction_aware_and_negative_in_the_money():
    t = _table(STANDARD)
    low, high = _row(t, 22700.0), _row(t, 22850.0)
    assert low["call"]["itm"] and not low["put"]["itm"]
    assert high["put"]["itm"] and not high["call"]["itm"]
    assert low["call"]["moneyness_pct"] == pytest.approx((22700.0 - SPOT) / SPOT * 100, abs=0.01)
    assert low["put"]["moneyness_pct"] == pytest.approx((SPOT - 22700.0) / SPOT * 100, abs=0.01)


def test_the_rate_card_is_stated_without_a_slippage_it_does_not_charge():
    card = _table(STANDARD)["rate_card"]
    assert "₹20 an order" in card and "0.15% STT" in card and "slippage" not in card


# --- fetching ---------------------------------------------------------------------

class _FakeNSE:
    def __init__(self, expiries):
        self.expiries, self.asked = expiries, []

    def option_chain_contract_info(self, symbol):
        return {"expiryDates": self.expiries, "strikePrice": []}

    def index_option_chain(self, symbol, expiry=None):
        self.asked.append((symbol, expiry))
        return _payload(STANDARD)


def test_the_nearest_expiry_is_fetched_unless_another_is_asked_for(monkeypatch):
    nse = _FakeNSE([EXPIRY, "13-Oct-2026"])
    monkeypatch.setattr("market_data.live_quote._session", lambda: nse)
    t = ct.live_chain_table(today=TODAY)
    assert nse.asked == [("NIFTY", EXPIRY)] and t["expiries"] == [EXPIRY, "13-Oct-2026"]


def test_an_expiry_nse_does_not_list_is_refused_before_asking_for_its_chain(monkeypatch):
    nse = _FakeNSE([EXPIRY])
    monkeypatch.setattr("market_data.live_quote._session", lambda: nse)
    with pytest.raises(ct.UnknownExpiry):
        ct.live_chain_table("27-Jun-2031", today=TODAY)
    assert nse.asked == []


def test_the_endpoint_says_404_for_an_unknown_expiry_and_503_when_nse_fails(monkeypatch):
    import main

    def unknown(expiry=None, today=None):
        raise ct.UnknownExpiry(f"NSE lists no NIFTY expiry {expiry}")

    def down(expiry=None, today=None):
        raise RuntimeError("NSE returned no option-chain records")

    monkeypatch.setattr(main, "live_chain_table", unknown)
    with pytest.raises(HTTPException) as e:
        main.options_chain_contracts(expiry="01-Jan-2031")
    assert e.value.status_code == 404
    monkeypatch.setattr(main, "live_chain_table", down)
    with pytest.raises(HTTPException) as e:
        main.options_chain_contracts(expiry="02-Jan-2031")
    assert e.value.status_code == 503


# --- open interest, folded in from the old card (2026-09-29) --------------------

OI_ROWS = [(22700.0, _side(22700.0, oi=4000, oi_chg=100), _side(22700.0, kind="PE", oi=9000, oi_chg=-300)),
           (22800.0, _side(22800.0, oi=7000, oi_chg=500), _side(22800.0, kind="PE", oi=6000, oi_chg=200)),
           (22900.0, _side(22900.0, oi=12000, oi_chg=900), ABSENT)]


def test_the_chain_carries_the_open_interest_summary_for_its_own_expiry():
    oi = _table(OI_ROWS)["open_interest"]
    assert (oi["total_call"], oi["total_put"]) == (23000, 15000)
    assert oi["pcr"] == round(15000 / 23000, 3)
    assert (oi["max_call_oi_strike"], oi["max_put_oi_strike"]) == (22900.0, 22700.0)
    assert (oi["call_oi_added"], oi["put_oi_added"]) == (1500, -100)


def test_the_summary_matches_what_the_open_interest_card_showed():
    """The chain replaces the open-interest card on the Today tab, so on the
    same NSE payload it must say what that card said."""
    from options.chain_analytics import analyse_chain
    old = analyse_chain(_payload(OI_ROWS), EXPIRY)
    oi = _table(OI_ROWS)["open_interest"]
    assert (oi["total_call"], oi["total_put"], oi["pcr"]) == (old.total_call_oi, old.total_put_oi, old.pcr_oi)
    assert (oi["max_call_oi_strike"], oi["max_put_oi_strike"]) == (old.max_call_oi_strike, old.max_put_oi_strike)
    assert (oi["call_oi_added"], oi["put_oi_added"]) == (old.call_oi_added, old.put_oi_added)


def test_a_chain_with_no_call_open_interest_has_no_ratio():
    oi = _table([(22800.0, _side(22800.0, oi=0), _side(22800.0, kind="PE", oi=500))])["open_interest"]
    assert oi["pcr"] is None and oi["max_call_oi_strike"] is None and oi["max_put_oi_strike"] == 22800.0
