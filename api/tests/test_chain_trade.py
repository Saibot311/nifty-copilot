"""The option-chain trade (options/chain_trade.py) and its log (storage/chain_trade_db.py)."""

import sqlite3

import pytest

from options.chain_trade import DEFAULT_RULES, Rules, build_trade, parse_rules
from storage import chain_trade_db


def contract(strike, kind, oi=1000, oi_change=0, iv=14.0, ask=100.0):
    buyer = {"price": ask, "price_source": "ask", "lot_rs": ask * 65, "charges_rs": 60.0,
             "breakeven": strike + ask if kind == "CE" else strike - ask} if ask else None
    return {"identifier": f"OPTIDXNIFTY{kind}{strike:g}", "oi": oi, "oi_change": oi_change, "iv": iv,
            "ltp": ask, "buyer": buyer}


def table(call_add=0, put_add=0, pcr=1.0, iv=14.0, ask=100.0, spot=25000.0, step=50, n=21):
    """A chain of n strikes centred on spot; the build-up sits on the ATM strike."""
    atm = round(spot / step) * step
    rows = []
    for k in range(-(n // 2), n // 2 + 1):
        s = float(atm + k * step)
        at = k == 0
        rows.append({"strike": s, "is_atm": at,
                     "call": contract(s, "CE", oi_change=call_add if at else 0, iv=iv, ask=ask),
                     "put": contract(s, "PE", oi_change=put_add if at else 0, iv=iv, ask=ask)})
    return {"expiry": "20-Oct-2026", "as_of": "12-Oct-2026 12:30:00", "underlying_value": spot,
            "atm_strike": float(atm), "lot_size": 65, "open_interest": {"pcr": pcr}, "rows": rows}


# 11 strikes near the money each hold 2,000 contracts: 22,000 in all, so 1,000 is a 4.5% skew.
def test_puts_built_faster_buys_the_atm_call():
    r = build_trade(table(put_add=1000))
    assert r["action"] == "BUY_CE"
    t = r["trade"]
    assert (t["side"], t["strike"]) == ("CE", 25000.0)
    assert t["entry"] == 100.0 and t["target"] == 140.0 and t["stop"] == 75.0
    assert r["inputs"]["skew_pct"] == pytest.approx(4.55, abs=0.01)
    assert "support below" in t["rationale"]


def test_calls_built_faster_buys_the_put_out_of_the_money_by_offset():
    r = build_trade(table(call_add=1000), Rules(strike_offset=2))
    assert r["action"] == "BUY_PE"
    assert r["trade"]["strike"] == 24900.0  # two steps below the money for a put


def test_even_build_up_is_no_trade():
    r = build_trade(table(call_add=500, put_add=600))
    assert r["action"] == "NO_TRADE" and r["trade"] is None
    assert "under the 2% bar" in r["reason"]


def test_pcr_contradicting_the_build_up_is_no_trade():
    assert build_trade(table(put_add=1000, pcr=0.6))["action"] == "NO_TRADE"
    assert build_trade(table(call_add=1000, pcr=1.5))["action"] == "NO_TRADE"


def test_missing_pcr_is_no_trade_not_a_guess():
    assert "PCR is missing" in build_trade(table(put_add=1000, pcr=None))["reason"]


def test_dear_iv_is_no_trade_and_missing_iv_is_said():
    assert "dear" in build_trade(table(put_add=1000, iv=35.0))["reason"]
    r = build_trade(table(put_add=1000, iv=None))
    assert r["action"] == "BUY_CE" and "IV not reported" in r["trade"]["rationale"]


def test_no_price_leaves_entry_target_and_stop_missing():
    t = build_trade(table(put_add=1000, ask=None))["trade"]
    assert t["entry"] is None and t["target"] is None and t["stop"] is None


def test_target_and_stop_land_on_the_tick():
    t = build_trade(table(put_add=1000, ask=101.3))["trade"]
    assert t["target"] == 141.8 and t["stop"] == 76.0


def test_rules_parse_and_default_flag():
    assert parse_rules({}) == DEFAULT_RULES
    r = parse_rules({"target_pct": 60.0, "stop_pct": None, "unknown": 1})
    assert r.target_pct == 60.0 and r.stop_pct == DEFAULT_RULES.stop_pct
    assert build_trade(table(put_add=1000), r)["default_rules"] is False


def test_log_keeps_the_first_suggestion_of_a_session_and_refuses_edits(tmp_path):
    db = tmp_path / "chain_trade.db"
    assert chain_trade_db.add_suggestion("2026-10-12", "10:00", {"action": "BUY_CE"}, db_path=db)
    assert not chain_trade_db.add_suggestion("2026-10-12", "11:00", {"action": "BUY_PE"}, db_path=db)
    assert chain_trade_db.suggestions(db_path=db)[0]["action"] == "BUY_CE"
    with pytest.raises(sqlite3.DatabaseError), chain_trade_db.connect(db) as conn:
        conn.execute("DELETE FROM suggestions")


# --- sizing and levels --------------------------------------------------------------

from datetime import datetime

from market_data.kite_session import IST

NOW = datetime(2026, 10, 12, 12, 30, tzinfo=IST)


def with_walls(t, put_strike=24900.0, call_strike=25100.0):
    """Extra OI added today at a strike below spot (puts) and above it (calls)."""
    for r in t["rows"]:
        if r["strike"] == put_strike:
            r["put"]["oi_change"] += 800
        if r["strike"] == call_strike:
            r["call"]["oi_change"] += 900
        if r["strike"] == 24800.0:
            r["put"]["oi_change"] += 300  # a smaller wall: not the one chosen
    return t


# one lot: 100 x 65 = 6,500 + 60 charges; risk at the stop: 25 x 65 + 60 = 1,685.
def test_sizing_is_none_without_capital():
    assert build_trade(table(put_add=1000))["trade"]["sizing"] is None


def test_sizing_limited_by_money():
    s = build_trade(table(put_add=1000), capital=9000, risk_pct=20)["trade"]["sizing"]
    assert s["lot_cost_rs"] == 6560.0 and s["affordable_lots"] == 1 and s["lots_by_risk"] == 1
    assert s["risk_per_lot_rs"] == 1685.0
    assert s["lots"] == 1 and s["limited_by"] == "money" and s["quantity"] == 65
    assert s["deployed_rs"] == 6560.0 and s["max_loss_rs"] == 1685.0
    assert s["profit_at_target_rs"] == 40 * 65 - 60  # 2,540
    assert s["note"] is None


def test_sizing_limited_by_risk():
    s = build_trade(table(put_add=1000), capital=50000, risk_pct=5)["trade"]["sizing"]
    assert s["affordable_lots"] == 7 and s["lots_by_risk"] == 1  # 2,500 / 1,685
    assert s["lots"] == 1 and s["limited_by"] == "risk" and s["max_loss_rs"] == 1685.0


def test_sizing_zero_lot_notes():
    poor = build_trade(table(put_add=1000), capital=5000)["trade"]["sizing"]
    assert poor["lots"] == 0 and poor["quantity"] == 0 and poor["max_loss_rs"] == 0
    assert "buys no lot" in poor["note"] and "₹6,560" in poor["note"]
    tight = build_trade(table(put_add=1000), capital=50000, risk_pct=2)["trade"]["sizing"]
    assert tight["lots"] == 0 and "more than 2%" in tight["note"] and "₹1,685" in tight["note"]


def test_sizing_needs_a_price():
    assert build_trade(table(put_add=1000, ask=None), capital=50000)["trade"]["sizing"] is None


def test_ce_levels_use_the_strongest_put_wall_below_spot():
    lv = build_trade(with_walls(table(put_add=1000)), now=NOW)["trade"]["levels"]
    assert lv["support"] == 24900.0 and lv["ceiling"] == 25100.0
    assert lv["enter_above"] == 24900.0 and "enter_below" not in lv
    assert lv["entry_condition"] == "Consider entering while NIFTY holds above 24,900"
    assert lv["entry_max_premium"] == 103.0
    assert lv["invalidation_index"] == 24900.0 and "closes below 24,900" in lv["invalidation_text"]
    assert lv["time_exit_by"] == "15:15" and "15:15" in lv["time_exit"]


def test_pe_levels_mirror_with_the_call_wall():
    lv = build_trade(with_walls(table(call_add=1000)), now=NOW)["trade"]["levels"]
    assert lv["enter_below"] == 25100.0 and "holds below 25,100" in lv["entry_condition"]
    assert lv["invalidation_index"] == 25100.0 and "closes above 25,100" in lv["invalidation_text"]


def test_index_equivalents_follow_delta():
    for build, up in ((lambda: table(put_add=1000), True), (lambda: table(call_add=1000), False)):
        lv = build_trade(with_walls(build()), now=NOW)["trade"]["levels"]
        d = lv["delta"]
        assert d is not None and 0.2 < abs(d) < 0.8
        sign = 1 if up else -1
        assert lv["exit_target_index"] == round(25000 + sign * 40 / abs(d))
        assert lv["exit_stop_index"] == round(25000 - sign * 25 / abs(d))
        assert (lv["exit_target_index"] > 25000) is up and (lv["exit_stop_index"] < 25000) is up
        assert "about NIFTY" in lv["exit_target_text"] and "must" not in lv["exit_target_text"]


def test_no_wall_falls_back_to_a_quarter_percent():
    lv = build_trade(table(put_add=1000), now=NOW)["trade"]["levels"]  # only ATM has changes
    assert lv["support"] is None and lv["enter_above"] == 24938  # 25000 less 0.25%
    assert lv["invalidation_index"] is None and lv["invalidation_text"] is None


def test_no_clock_means_no_delta_and_premium_levels_only():
    lv = build_trade(with_walls(table(put_add=1000)))["trade"]["levels"]
    assert lv["delta"] is None and lv["exit_target_index"] is None and lv["exit_stop_index"] is None
    assert "premium levels only" in lv["exit_target_text"] and "₹140.00" in lv["exit_target_text"]


def test_expiry_day_exits_earlier():
    t = with_walls(table(put_add=1000))
    t["expiry"] = "12-Oct-2026"
    lv = build_trade(t, now=NOW)["trade"]["levels"]
    assert lv["time_exit_by"] == "14:30" and "expiry day" in lv["time_exit"]
