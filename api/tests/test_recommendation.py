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
        # The other families are fixed at today's counts, so these tests do not
        # move when a study on disk is re-run.
        def family(r):
            n = sum(1 for p in (r or {}).get("patterns", []) if (p.get("holdout") or {}).get("num_trades"))
            f = {"patterns": n, "iv_filter": 1, "structural": 6, "replication": 22, "news_tone": 5}
            return {**f, "total": sum(f.values())}
        monkeypatch.setattr(rec_mod, "holdout_family", family)
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
    wire(_prox(("alpha", "PE")), _research(alpha=("APPROVED", 5.0)))
    r = rec_mod.build_recommendation()
    assert r["action"] == "CONSIDER_PUT"
    assert "Buy ATM option for alpha" in r["headline"]


def test_opposite_proven_setups_on_one_close_stand_aside(wire):
    # Both well clear of the bar (t 3.5 and 3.4 were, until the bar counted
    # all 53 hypotheses; now only one would be, which is a different test).
    wire(_prox(("alpha", "CE"), ("beta", "PE")), _research(alpha=("APPROVED", 5.0), beta=("APPROVED", 4.8)))
    assert rec_mod.build_recommendation()["action"] == "NO_TRADE"


def test_missing_research_is_no_trade(wire):
    wire(_prox(("alpha", "CE")), None)
    assert rec_mod.build_recommendation()["action"] == "NO_TRADE"


def test_the_bar_counts_every_hypothesis_that_has_looked_at_the_holdout(wire, monkeypatch):
    """I5. The gate used to count patterns, the IV filter and the structural
    six (26), and left out the 22 replications and the 5 news-tone tests,
    though each of those also had its one look at 2024-26. The bar it showed
    was 2.89 where the 53 hypotheses judged call for 3.11."""
    import backtest.iv_research as iv
    import backtest.news_research as nr
    import backtest.replication as rp
    import backtest.structural_research as sr
    from stats.multiple_comparisons import required_t

    monkeypatch.setattr(iv, "load_iv_research", lambda: {"preregistered_test": {}})
    monkeypatch.setattr(sr, "load_structural_research", lambda: {"hypotheses": [{}] * 6})
    monkeypatch.setattr(rp, "load_replication", lambda: {"hypotheses": [{}] * 22})
    monkeypatch.setattr(nr, "load_news_research", lambda: {"hypotheses": [{}] * 5})
    research = {"patterns": [{"strategy": f"p{i}", "status": "REJECTED", "holdout": {"num_trades": 12}} for i in range(19)]
                + [{"strategy": "never_formed", "status": "REJECTED", "holdout": {"num_trades": 0}}]}
    wire(_prox(), research)
    from backtest.family import holdout_family
    monkeypatch.setattr(rec_mod, "holdout_family", holdout_family)  # the real count, not the fixture's
    bar = rec_mod.build_recommendation()["evidence_bar"]
    assert bar["tests_judged"] == 19 + 1 + 6 + 22 + 5 == 53
    assert bar["min_t"] == required_t(53) == 3.11
    assert bar["family"] == {"patterns": 19, "iv_filter": 1, "structural": 6, "replication": 22, "news_tone": 5}


def test_after_the_close_the_next_close_is_not_called_the_next_one(wire, monkeypatch):
    """Between 15:30 and the evening job, the last close in the data is
    yesterday's while today's has already happened. "Could form on the next
    close" then pointed at a close that was over."""
    from datetime import datetime
    from market_data.live_quote import IST
    wire(_prox(), _research())  # as_of 2026-09-17, a Thursday
    monkeypatch.setattr(rec_mod, "_now", lambda: datetime(2026, 9, 18, 17, 0, tzinfo=IST), raising=False)
    r = rec_mod.build_recommendation()
    assert "today's close" in r["reason"] and "not in the data yet" in r["reason"]
    monkeypatch.setattr(rec_mod, "_now", lambda: datetime(2026, 9, 18, 11, 0, tzinfo=IST))
    assert "next close" in rec_mod.build_recommendation()["reason"]
