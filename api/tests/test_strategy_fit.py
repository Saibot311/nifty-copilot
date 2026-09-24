"""Which strategies today's market suits — Jev's reading of the conditions,
next to Python's own account of whether each one is actually forming.

Python decides what is forming (arithmetic on real prices). Jev is asked
only whether today's conditions are the kind each strategy's premise was
written for. It never sees a strategy's record or its trigger, is never asked
about returns or direction, and nothing it says reaches the recommendation
or the paper book. No Jev call is made in these tests."""

from datetime import datetime, timedelta

import pytest

import market_engine.strategy_fit as sf
from copilot import jev

PROX = {"as_of": "2026-09-24", "regime": "TREND_BEAR", "patterns": [
    {"strategy": "prev_day_breakdown", "label": "Prev-Day-Low Breakdown", "option_type": "PE", "direction": "short",
     "formed_today": True, "probability_next": 0.395,
     "trigger": {"close_ranges_level": [[22371, 23046]]}, "forms_when": "Close below yesterday's low.", "why": "Momentum."},
    {"strategy": "stochastic_oversold_reversal", "label": "Stochastic Oversold Reversal", "option_type": "CE",
     "direction": "long", "formed_today": False, "probability_next": 0.204,
     "trigger": {"close_ranges_level": [[23215, 23755]]}, "forms_when": "Stochastic crosses up below 20.", "why": "Bounce."},
    {"strategy": "prev_day_breakout", "label": "Prev-Day-High Breakout", "option_type": "CE", "direction": "long",
     "formed_today": False, "probability_next": 0.01,
     "trigger": {"close_ranges_level": [[23900, 24400]]}, "forms_when": "Close above yesterday's high.", "why": "Breakout."},
    {"strategy": "ema_pullback", "label": "EMA Pullback", "option_type": "CE", "direction": "long",
     "formed_today": False, "probability_next": 0.0, "trigger": None, "forms_when": "Pullback to EMA20.", "why": "Trend."},
    {"strategy": "pcr_capitulation_call", "label": "PCR Capitulation", "option_type": "CE", "direction": "long",
     "formed_today": None, "probability_next": None, "trigger": None, "forms_when": "PCR > 1.5.", "why": "Contrarian."},
]}
MARKET = {"index": {"level": 23063.1, "change_pct": -1.64, "as_of": "the 2026-09-24 close"}, "trend": "TREND_BEAR"}


def test_the_shortlist_is_what_is_actually_forming_or_within_reach():
    rows = sf.shortlist(PROX, live_rows=[], index_now=23063.1)
    names = [r["strategy"] for r in rows]
    assert names[0] == "prev_day_breakdown" and rows[0]["status"] == "formed"
    assert "stochastic_oversold_reversal" in names          # trigger 0.66% away, and forms on 20% of days
    assert "prev_day_breakout" not in names and "ema_pullback" not in names   # 3.6% away / never near
    assert "pcr_capitulation_call" not in names             # cannot be simulated from price at all


def test_a_live_would_form_now_leads_the_list():
    live = [{"strategy": "prev_day_breakout", "would_form_now": True, "pct_to_trigger": None}]
    rows = sf.shortlist(PROX, live_rows=live, index_now=23950.0)
    assert rows[0]["strategy"] == "prev_day_breakout" and rows[0]["status"] == "forming now"


def test_jev_is_asked_about_conditions_only():
    rows = sf.shortlist(PROX, live_rows=[], index_now=23063.1)
    state = sf.jev_state(MARKET, rows)
    blob = str(state).lower()
    # It sees the market and each premise — never a record, a verdict, a trigger or a status.
    for leaked in ("rejected", "holdout", "t_stat", "trigger", "formed", "status", "probability_next"):
        assert leaked not in blob, leaked
    qs = sf.questions(rows)
    assert set(qs) == {f"fit__{r['strategy']}" for r in rows}
    for q in qs.values():
        assert q["type"] == "noul"
        text = str(q).lower()
        assert "will make money" not in text and "profit" not in text


def test_answers_are_read_and_a_missing_one_is_unjudged_not_zero(monkeypatch):
    rows = sf.shortlist(PROX, live_rows=[], index_now=23063.1)
    monkeypatch.setattr(jev, "ask", lambda state, questions: {"fit__prev_day_breakdown": {"type": "noul", "noul": 0.81}})
    fits = sf.judge(MARKET, rows)
    assert fits["prev_day_breakdown"] == 0.81 and fits["stochastic_oversold_reversal"] is None


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr(sf, "DB_PATH", tmp_path / "fit.db")
    calls = []
    monkeypatch.setattr(jev, "available", lambda: True)
    monkeypatch.setattr(jev, "ask", lambda state, questions: calls.append(1) or
                        {q: {"type": "noul", "noul": 0.5} for q in questions})
    monkeypatch.setattr(sf, "_inputs", lambda: (MARKET, PROX, [], 23063.1))
    return calls


def test_a_paid_call_is_made_at_most_every_fifteen_minutes_and_not_for_an_unchanged_market(world, monkeypatch):
    t0 = datetime(2026, 9, 25, 11, 0, tzinfo=sf.IST)
    first = sf.reading(now=t0)
    assert len(world) == 1 and first["judged"] is True
    sf.reading(now=t0 + timedelta(minutes=5))                 # too soon
    sf.reading(now=t0 + timedelta(minutes=40))                # same market: the stored reading stands
    assert len(world) == 1
    moved = {**MARKET, "trend": "RANGE"}
    monkeypatch.setattr(sf, "_inputs", lambda: (moved, PROX, [], 23063.1))
    sf.reading(now=t0 + timedelta(minutes=10))                # changed, but still within fifteen minutes
    assert len(world) == 1
    sf.reading(now=t0 + timedelta(minutes=20))
    assert len(world) == 2


def test_without_jev_the_forming_part_still_stands(world, monkeypatch):
    monkeypatch.setattr(jev, "available", lambda: False)
    r = sf.reading(now=datetime(2026, 9, 25, 11, 0, tzinfo=sf.IST))
    assert r["judged"] is False and r["rows"] and all(x["fit"] is None for x in r["rows"])
    assert r["rows"][0]["status"] == "formed"


def test_nothing_here_reaches_the_recommendation_or_the_paper_book():
    import inspect

    import briefing.paper as paper
    import briefing.recommendation as rec
    for module in (rec, paper):
        assert "strategy_fit" not in inspect.getsource(module)
