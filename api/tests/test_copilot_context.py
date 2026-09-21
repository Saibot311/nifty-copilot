"""Route-scoped context. The thing to guard is that narrowing never drops
what an answer needs: the core is always there, an unsure route gets
everything, and the record view carries every pattern rather than only the
ones near firing today."""

import pytest

import copilot.context as ctxmod
import copilot.router as router

PROX = {
    "as_of": "2026-09-18", "last_close": 23346.4, "regime": "TREND_BEAR",
    "patterns": [
        {"strategy": "rsi_reversal", "label": "RSI Oversold Reversal", "option_type": "CE",
         "formed_today": True, "probability_next": None, "forms_when": "...", "why": "..."},
        {"strategy": "prev_day_breakout", "label": "Prev-Day-High Breakout", "option_type": "CE",
         "formed_today": False, "probability_next": 0.3, "forms_when": "...", "why": "..."},
        {"strategy": "bollinger_reversion", "label": "Bollinger Band Reversion", "option_type": "CE",
         "formed_today": False, "probability_next": 0.0, "forms_when": "...", "why": "..."},
    ],
}
REC = {"action": "NO_TRADE", "headline": "No trade", "reason": "Nothing formed.",
       "evidence_bar": {"min_t": 2.9, "patterns_judged": 26}}
RESEARCH = {"patterns": [
    {"strategy": "rsi_reversal", "label": "RSI Oversold Reversal", "option_type": "CE", "forms_per_year": 4.0,
     "status": "REJECTED", "holdout_t_stat": 0.74, "suggested_option": {"description": "Buy 2% ITM CE"},
     "holdout": {"num_trades": 28, "win_rate": 0.5, "avg_profit_per_lot_rs": -1170}},
    {"strategy": "bollinger_reversion", "label": "Bollinger Band Reversion", "option_type": "CE",
     "forms_per_year": 5.9, "status": "CONDITIONAL", "holdout_t_stat": 0.86,
     "suggested_option": {"description": "Buy 2% ITM CE"},
     "holdout": {"num_trades": 11, "win_rate": 0.455, "avg_profit_per_lot_rs": 3667}},
    {"strategy": "ema_pullback", "label": "EMA Pullback (long)", "option_type": "CE", "forms_per_year": 30.0,
     "status": "REJECTED", "suggested_option": {"description": "Buy ATM CE"}, "holdout": {}},
]}
LIVE = {"candle": {"close": 23300.0}, "provisional": True, "basis": "15m", "change_pct": -0.2, "patterns": []}


@pytest.fixture(autouse=True)
def stub(monkeypatch):
    calls = {"similarity": 0}
    monkeypatch.setattr(ctxmod, "cached", lambda key, ttl_seconds, producer: producer())
    monkeypatch.setattr(ctxmod, "build_recommendation", lambda symbol: REC)
    monkeypatch.setattr(ctxmod, "pattern_proximity", lambda symbol: PROX)
    monkeypatch.setattr(ctxmod, "load_research", lambda: RESEARCH)
    monkeypatch.setattr(ctxmod, "forward_report", lambda symbol: {"summary": {"days_logged": 2}})

    def similarity(symbol):
        calls["similarity"] += 1
        return {"analogs": [], "outcomes": {}, "walk_forward": {"verdict": "no demonstrated value"}}

    monkeypatch.setattr(ctxmod, "run_similarity", similarity)
    return calls


CORE = {"fixed_facts", "as_of_close", "last_close", "regime", "recommendation", "how_it_decides"}


@pytest.mark.parametrize("scope", [None, "today", "pattern_record", "method", "nonsense"])
def test_the_core_is_in_every_view(scope):
    assert CORE <= set(ctxmod.build_context(scope=scope))


def test_an_unknown_or_missing_scope_gets_the_full_dashboard():
    # The daily explanation passes no scope, and must not be narrowed.
    assert set(ctxmod.build_context()) == set(ctxmod.build_context(scope="today"))
    assert set(ctxmod.build_context(scope="nonsense")) == set(ctxmod.build_context(scope="today"))


def test_the_record_view_carries_every_pattern_not_just_todays():
    # The bug this exists for: asked which pattern had the best record, the
    # copilot could only see the ones near firing and named a loss-maker.
    c = ctxmod.build_context(scope="pattern_record")
    names = [p["name"] for p in c["every_pattern_researched"]]
    assert set(names) == {"RSI Oversold Reversal", "Bollinger Band Reversion", "EMA Pullback (long)"}
    # Best measured record first, so the answer to "which is best" is there.
    assert names[0] == "Bollinger Band Reversion"


def test_an_unmeasured_pattern_is_marked_not_dropped():
    # "Not measured" is a different answer from "did badly".
    rows = {p["name"]: p for p in ctxmod.build_context(scope="pattern_record")["every_pattern_researched"]}
    assert rows["EMA Pullback (long)"]["measured"] is False
    assert rows["Bollinger Band Reversion"]["measured"] is True
    assert rows["EMA Pullback (long)"]["name"] == ctxmod.build_context(
        scope="pattern_record")["every_pattern_researched"][-1]["name"]


def test_the_method_view_drops_pattern_lists_and_live_data():
    c = ctxmod.build_context(live=LIVE, scope="method")
    assert "patterns_formed_on_last_close" not in c and "live_now" not in c
    assert "similar_past_days" in c and c["how_it_decides"]["verdicts"]["REJECTED"]


def test_the_record_view_does_not_wait_for_the_analog_search(stub):
    ctxmod.build_context(scope="pattern_record")
    assert stub["similarity"] == 0
    ctxmod.build_context(scope="today")
    assert stub["similarity"] == 1


def test_live_data_only_reaches_the_views_that_use_it():
    assert "live_now" in ctxmod.build_context(live=LIVE, scope="today")
    assert "live_now" not in ctxmod.build_context(live=LIVE, scope="pattern_record")


# --- the router decides the scope, but only when it is sure -------------------

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _route_resp(**probs):
    return _Resp({"answers": {"route": {"type": "choice", "confidence": 0.9,
                                        "choice": max(probs, key=probs.get), "probabilities": probs}}})


@pytest.fixture
def jev_key(monkeypatch):
    import copilot.jev as jev
    monkeypatch.setattr(jev, "_env", lambda k: "ts-key" if k == "TYPESAFE_API_KEY" else None)
    return jev


def test_a_confident_route_narrows_the_context(jev_key, monkeypatch):
    monkeypatch.setattr(jev_key.requests, "post", lambda *a, **k: _route_resp(
        today=0.05, pattern_record=0.92, method=0.02, off_topic=0.01))
    assert router.route("which pattern is best?")["scope"] == "pattern_record"


def test_an_unsure_route_sends_everything(jev_key, monkeypatch):
    # A wrong slice removes the very facts the answer needs, so uncertainty
    # falls back to the behaviour from before routing existed.
    monkeypatch.setattr(jev_key.requests, "post", lambda *a, **k: _route_resp(
        today=0.45, pattern_record=0.4, method=0.1, off_topic=0.05))
    r = router.route("what about bollinger?")
    assert r["route"] == "today" and r["scope"] is None


def test_a_router_outage_sends_everything(monkeypatch):
    import copilot.jev as jev
    monkeypatch.setattr(jev, "_env", lambda k: None)
    assert router.route("why no trade?")["scope"] is None
