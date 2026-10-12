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
