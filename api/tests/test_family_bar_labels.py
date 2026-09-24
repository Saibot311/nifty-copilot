"""The labels on screen face the same bar as the recommendation.

The gate re-applied Bonferroni before anything reached the Today tab, but the
Research tab's pattern verdicts, the index-level validation (Playbook) and
the similar-days card each judged at t >= 2 — so a label could read APPROVED
or "has predicted well" at a t the gate would refuse. Decided with the user
on 2026-09-24: every such label uses the family bar (53 hypotheses -> 3.11 in
the large-sample limit, more on few trades)."""

import pytest

from stats.multiple_comparisons import required_t


@pytest.fixture
def family_of_53(monkeypatch):
    import backtest.family as fam
    monkeypatch.setattr(fam, "holdout_family", lambda research=None: {"total": 53})


def _pattern(t, n=30):
    return {"strategy": "x", "label": "X", "direction": "long", "option_type": "CE",
            "development": {"avg_profit_per_lot_rs": 900, "num_trades": 40},
            "holdout": {"avg_profit_per_lot_rs": 800, "num_trades": n},
            "baseline": {"development_avg_profit_per_lot_rs": 100, "holdout_avg_profit_per_lot_rs": -200},
            "holdout_t_stat": t, "status": "APPROVED", "reason": "old"}


def test_a_pattern_verdict_faces_the_family_bar():
    import backtest.pattern_options as po
    weak, strong = _pattern(2.5), _pattern(5.0)
    po.apply_family_bar([weak, strong], tests=53)
    assert weak["status"] == "REJECTED" and weak["required_t"] == required_t(53, df=29)
    assert strong["status"] == "APPROVED"


def test_index_validation_faces_the_family_bar(family_of_53):
    import backtest.walkforward as wf
    assert wf.family_bar(60) == required_t(53, df=59) > 3
    assert wf.family_bar(1) is None


def test_the_similar_days_card_faces_the_family_bar(family_of_53):
    import backtest.similarity as sim
    assert sim.predictive_bar() == required_t(53) == 3.11
    assert sim.verdict(2.5)["predictive"] is False
    assert sim.verdict(3.5)["predictive"] is True and "3.11" in sim.verdict(3.5)["verdict"]
