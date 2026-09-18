"""The recommendation gate: a trade only when a pattern formed on the last
final close AND its option verdict is APPROVED AND its t clears the
Bonferroni bar. Every other path must say NO TRADE."""

import pytest

import briefing.recommendation as rec_mod


def _prox(*formed):
    patterns = [
        {"strategy": name, "label": name.title(), "direction": "long" if ot == "CE" else "short",
         "option_type": ot, "formed_today": True, "probability_next": None}
        for name, ot in formed
    ]
    patterns.append({"strategy": "idle", "label": "Idle", "direction": "long", "option_type": "CE",
                     "formed_today": False, "probability_next": 0.3})
    return {"as_of": "2026-09-17", "regime": "TREND_BEAR", "patterns": patterns}


def _research(**verdicts):
    """verdicts: name -> (status, t). 26 patterns judged, so the bar is ~2.9."""
    patterns = [{"strategy": f"filler{i}", "status": "REJECTED", "holdout": {"num_trades": 20}} for i in range(26)]
    for name, (status, t) in verdicts.items():
        patterns.append({
            "strategy": name, "status": status, "holdout_t_stat": t, "reason": "r",
            "suggested_option": {"description": f"Buy ATM option for {name}"},
            "holdout": {"num_trades": 30, "avg_profit_per_lot_rs": 2500},
        })
    return {"patterns": patterns}


@pytest.fixture
def wire(monkeypatch):
    def _wire(prox, research):
        monkeypatch.setattr(rec_mod, "cached", lambda key, ttl_seconds, producer: prox)
        monkeypatch.setattr(rec_mod, "load_research", lambda: research)
    return _wire


def test_nothing_formed_is_no_trade_and_mentions_what_could_form(wire):
    wire(_prox(), _research())
    r = rec_mod.build_recommendation()
    assert r["action"] == "NO_TRADE" and "Idle" in r["reason"]


def test_formed_but_rejected_is_no_trade(wire):
    wire(_prox(("alpha", "CE")), _research(alpha=("REJECTED", 0.4)))
    r = rec_mod.build_recommendation()
    assert r["action"] == "NO_TRADE" and r["candidates"][0]["why_not"] == "option verdict REJECTED"


def test_approved_at_t_2_is_not_enough_across_many_patterns(wire):
    wire(_prox(("alpha", "CE")), _research(alpha=("APPROVED", 2.3)))
    r = rec_mod.build_recommendation()
    assert r["action"] == "NO_TRADE"
    assert r["evidence_bar"]["min_t"] > 2.3


def test_approved_above_the_bonferroni_bar_is_a_trade_with_its_option(wire):
    wire(_prox(("alpha", "PE")), _research(alpha=("APPROVED", 3.5)))
    r = rec_mod.build_recommendation()
    assert r["action"] == "CONSIDER_PUT"
    assert "Buy ATM option for alpha" in r["headline"]


def test_opposite_proven_setups_on_one_close_stand_aside(wire):
    wire(_prox(("alpha", "CE"), ("beta", "PE")), _research(alpha=("APPROVED", 3.5), beta=("APPROVED", 3.4)))
    assert rec_mod.build_recommendation()["action"] == "NO_TRADE"


def test_missing_research_is_no_trade(wire):
    wire(_prox(("alpha", "CE")), None)
    assert rec_mod.build_recommendation()["action"] == "NO_TRADE"
