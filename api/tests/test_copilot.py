"""Phase 12 copilot. The guard is the point: the LLM may explain numbers the
system computed, never introduce its own. Tests never call a real provider."""

import pytest

import copilot.assistant as assistant
import copilot.llm_client as llm
from copilot.guard import numbers_in_text, unverified_numbers

@pytest.fixture(autouse=True)
def _log_to_a_temp_db(tmp_path, monkeypatch):
    """No test may write to the real copilot log."""
    import storage.copilot_log_db as log_db
    monkeypatch.setattr(log_db, "DB_PATH", tmp_path / "copilot_log.db")


DATA = {
    "last_close": 23270.6,
    "as_of_close": "2026-09-17",
    "fixed_facts": {"market_close_ist": "15:30", "lot_size": 65},
    "pattern": {"forms_on_close_between": [[23272, 23969]], "win_rate": 0.583, "avg_profit_per_lot_rs": -1170, "t_stat": 0.74},
    "similar": {"pct_higher": 0.7, "median_pct": 1.1},
}


# --- guard -----------------------------------------------------------------

def test_parses_indian_formatting_signs_and_decimals():
    assert numbers_in_text("₹1,170 and −0.48% on 23,270.60") == [1170.0, -0.48, 23270.6]


def test_numbers_from_data_pass_including_display_rounding():
    ok = ("NIFTY closed at 23,270.6 (about 23,271). It forms on a close of 23,272 to 23,969. "
          "Its option lost ₹1,170 per lot with a 58% win rate and t of 0.74. "
          "Similar days were 70% higher, median 1.1%. Lot size 65; market closes at 15:30 on 2026-09-17.")
    assert unverified_numbers(ok, DATA) == []


def test_invented_numbers_are_caught():
    bad = "NIFTY will probably reach 24,500 — a 65.2% chance, targeting ₹3,000 per lot."
    assert set(unverified_numbers(bad, DATA)) == {24500.0, 65.2, 3000.0}


def test_rounding_cannot_smuggle_a_different_number():
    # 23,300 is not a rendering of 23,270.6 at any precision the answer claims.
    assert unverified_numbers("around 23,300", DATA) == [23300.0]


def test_small_counting_numbers_and_the_users_own_numbers_are_allowed():
    assert unverified_numbers("Over the next 5 days, 2 patterns matter.", DATA) == []
    assert unverified_numbers("If NIFTY hits 24,000, nothing here changes.", DATA,
                              question="what if nifty hits 24000?") == []


# --- client ------------------------------------------------------------------

class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


@pytest.fixture
def env(monkeypatch):
    values = {"LLM_PROVIDER": "gemini", "LLM_API_KEY": "secret-key-123"}
    monkeypatch.setattr(llm, "_env", lambda k: values.get(k))
    return values


def test_missing_key_is_a_clear_not_configured_error(monkeypatch):
    monkeypatch.setattr(llm, "_env", lambda k: None)
    with pytest.raises(llm.LLMNotConfigured):
        llm.chat([{"role": "user", "content": "hi"}])


def test_provider_errors_never_echo_the_api_key(env, monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Resp(401, text="bad key secret-key-123"))
    with pytest.raises(llm.LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert "secret-key-123" not in str(e.value)


def test_rate_limit_gets_a_friendly_message(env, monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Resp(429))
    with pytest.raises(llm.LLMError, match="rate limit"):
        llm.chat([{"role": "user", "content": "hi"}])


# --- assistant ---------------------------------------------------------------

def test_one_retry_then_withhold_if_numbers_are_still_invented(monkeypatch):
    replies = iter(["NIFTY will hit 24,500.", "Fine: NIFTY will hit 24,800."])
    monkeypatch.setattr(assistant, "chat", lambda messages: next(replies))
    r = assistant._answer("what next?", DATA)
    # The rewrite is what gets reported, not the draft that preceded it.
    assert r["ok"] is False and r["answer"] is None and "24800" in r["reason"]


def test_retry_that_fixes_the_numbers_is_shown(monkeypatch):
    replies = iter(["NIFTY will hit 24,500.", "The system gives no target; it closed at 23,270.6."])
    monkeypatch.setattr(assistant, "chat", lambda messages: next(replies))
    r = assistant._answer("what next?", DATA)
    assert r["ok"] is True and "23,270.6" in r["answer"]


def test_explanation_is_saved_per_day_and_not_regenerated(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(assistant, "CACHE_PATH", tmp_path / "explain.json")
    monkeypatch.setattr(assistant, "build_context", lambda symbol, live=None, scope=None: DATA)
    monkeypatch.setattr(assistant, "chat", lambda messages: calls.append(1) or "It closed at 23,270.6.")
    first, second = assistant.explain_today(), assistant.explain_today()
    assert first["ok"] and not first["cached"] and second["cached"]
    # The daily explanation is drafted more than once and the better one
    # kept; the cache is what stops that happening twice in a day.
    assert len(calls) == assistant.EXPLAIN_DRAFTS


def test_every_number_in_the_data_passes_its_own_check():
    # Found on real data: 3-decimal fractions (0.452) were rejected, which
    # would have withheld honest answers that quote the data verbatim.
    import json

    data = {**DATA, "probability": 0.452, "hit": 0.001, "levels": [[22572, 23154]]}
    assert unverified_numbers(json.dumps(data), data) == []


# --- Jev client ---------------------------------------------------------------

import copilot.claim_guard as cg
import copilot.prediction_guard as pg
import copilot.jev as jev
import copilot.review as review
import copilot.router as router


@pytest.fixture
def jev_key(monkeypatch):
    monkeypatch.setattr(jev, "_env", lambda k: "ts-key" if k == "TYPESAFE_API_KEY" else None)


def test_no_key_is_unavailable_not_an_answer(monkeypatch):
    monkeypatch.setattr(jev, "_env", lambda k: None)
    with pytest.raises(jev.JevUnavailable):
        jev.ask("x", {"q": {"type": "noul", "instructions": "?"}})


def test_jev_errors_never_echo_the_key_or_the_body(jev_key, monkeypatch):
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _Resp(401, text="bad key ts-key"))
    with pytest.raises(jev.JevUnavailable) as e:
        jev.ask("x", {"q": {"type": "noul", "instructions": "?"}})
    assert "ts-key" not in str(e.value) and "bad key" not in str(e.value)


# --- forecast + claim review (one Jev call) -----------------------------------

def _answers(predicts=0.0, advises=0.0, claims=()):
    """claims: one (supported, contradicted, not_in_data, not_a_claim) tuple per sentence."""
    out = {"predicts_market": {"type": "noul", "noul": predicts},
           "advises_trade": {"type": "noul", "noul": advises}}
    for i, (sup, con, nid, nac) in enumerate(claims):
        out[f"claim_{i}"] = {"type": "choice", "choice": "supported",
                             "probabilities": {"supported": sup, "contradicted": con,
                                               "not_in_data": nid, "not_a_claim": nac}}
    return out


def _jev(predicts=0.0, advises=0.0, claims=()):
    return _Resp(200, {"model": "jev-1.13.0", "answers": _answers(predicts, advises, claims)})


def test_forecast_without_any_number_is_blocked(jev_key, monkeypatch):
    # The gap the number guard cannot cover: a prediction with no figures in it.
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _jev(0.91, 0.04))
    r = review.review_answer("The setup looks set to push higher from here.", check_claims=False)
    assert r["checked"] and r["blocked"] and "predicts" in r["reason"]


def test_explaining_the_systems_own_verdict_passes(jev_key, monkeypatch):
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _jev(0.04, 0.02))
    r = review.review_answer("The system says NO_TRADE because no pattern formed.", check_claims=False)
    assert r["checked"] and not r["blocked"]


def test_forecast_threshold_is_low_because_missing_one_is_the_costly_error(jev_key, monkeypatch):
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _jev(0.35, 0.0))
    assert review.review_answer("Momentum may carry it up.", check_claims=False)["blocked"] is True
    assert pg.BLOCK_ABOVE == 0.3


def test_both_guards_ride_one_request_over_shared_state(jev_key, monkeypatch):
    sent = {}
    monkeypatch.setattr(jev.requests, "post",
                        lambda url, **k: sent.update(k["json"]) or _jev(claims=[(1, 0, 0, 0)] * 2))
    review.review_answer("It closed at 23,270.6. The verdict is NO_TRADE.", DATA)
    # Both guards and both grades, in one request over one state.
    assert set(sent["questions"]) == {"predicts_market", "advises_trade", "claim_0", "claim_1",
                                      "honesty", "clarity"}
    assert sent["model"] == "jev-latest"
    # Richer state than the answer alone: the forecast questions can tell
    # reporting from predicting by checking what the system actually computed.
    assert set(sent["state"]) == {"answer", "claims", "data"}
    assert sent["state"]["data"] == DATA and len(sent["state"]["claims"]) == 2


def test_a_sentence_the_data_does_not_support_is_caught(jev_key, monkeypatch):
    # No invented number, no forecast — the hole the other two guards leave.
    monkeypatch.setattr(jev.requests, "post",
                        lambda *a, **k: _jev(claims=[(0.9, 0, 0.05, 0.05), (0.05, 0.05, 0.9, 0.0)]))
    r = review.review_answer("The verdict is NO_TRADE. Volatility has been high all month.", DATA)
    assert r["blocked"] and len(r["unsupported"]) == 1
    assert r["unsupported"][0]["claim"] == "Volatility has been high all month."
    assert "not supported" in r["problems"][0]


def test_framing_and_caveats_are_not_treated_as_claims(jev_key, monkeypatch):
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _jev(claims=[(0.1, 0.0, 0.05, 0.85)]))
    r = review.review_answer("None of this is a reason to trade.", DATA)
    assert not r["blocked"] and r["unsupported"] == []


def test_claim_threshold_is_looser_than_the_forecast_threshold():
    # Being twitchy here withholds honest answers; the number guard already
    # covers the dangerous case, so this one is not set to hair-trigger.
    assert cg.UNSUPPORTED_ABOVE > pg.BLOCK_ABOVE


def test_sentence_split_keeps_decimals_and_rupee_amounts_whole():
    parts = cg.split_claims('NIFTY closed at 23,270.60 today. It lost ₹1,170 per lot. "Rejected" means no edge.')
    assert parts == ["NIFTY closed at 23,270.60 today.", "It lost ₹1,170 per lot.",
                     '"Rejected" means no edge.']


def test_list_items_are_separate_claims():
    # Found live: a whole bulleted block came back as one claim, so a false
    # sentence could average out against true ones sitting beside it.
    parts = cg.split_claims("Two patterns formed:\n1. RSI Oversold (REJECTED)\n2. Stochastic (REJECTED)")
    assert parts == ["Two patterns formed:", "RSI Oversold (REJECTED)", "Stochastic (REJECTED)"]


def test_verdict_label_is_the_models_own_pick_not_a_tie_break(jev_key, monkeypatch):
    # Reporting "contradicted" on a sentence scored 1.0 supported reads as a
    # finding; the label has to match what the model actually chose.
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _Resp(200, {"answers": {
        "predicts_market": {"type": "noul", "noul": 0.0}, "advises_trade": {"type": "noul", "noul": 0.0},
        "claim_0": {"type": "choice", "choice": "supported",
                    "probabilities": {"supported": 1.0, "contradicted": 0.0, "not_in_data": 0.0, "not_a_claim": 0.0}}}}))
    r = review.review_answer("The verdict is NO_TRADE.", DATA)
    assert r["claims"][0]["verdict"] == "supported" and r["claims"][0]["against"] == 0.0


def test_claims_are_capped_so_one_answer_cannot_run_up_a_bill():
    long_answer = " ".join(f"Sentence number {i} is here." for i in range(40))
    assert len(cg.split_claims(long_answer)) == cg.MAX_CLAIMS


def test_no_key_skips_the_review_instead_of_blocking(monkeypatch):
    monkeypatch.setattr(jev, "_env", lambda k: None)
    r = review.review_answer("anything", DATA)
    assert r["checked"] is False and r["blocked"] is False


def test_guard_outage_never_blocks_the_copilot(jev_key, monkeypatch):
    def boom(*a, **k):
        raise jev.requests.RequestException("down")
    monkeypatch.setattr(jev.requests, "post", boom)
    r = review.review_answer("anything", DATA)
    assert r["checked"] is False and r["blocked"] is False and "unavailable" in r["reason"]


def test_assistant_withholds_an_answer_the_review_blocks(monkeypatch):
    monkeypatch.setattr(assistant, "chat", lambda messages: "Nothing formed, but it should bounce soon.")
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: {
        "checked": True, "blocked": True, "scores": {"predicts_market": 0.8}, "unsupported": [],
        "problems": ["This answer predicts where the market is going."],
        "reason": "Answer withheld: it predicts where the market is going, which this tool must not do."})
    r = assistant._answer("what now?", DATA)
    assert r["ok"] is False and r["answer"] is None and "predicts" in r["reason"]


def test_one_retry_fixes_an_unsupported_sentence(monkeypatch):
    replies = iter(["It closed at 23,270.6. Volatility has been high all month.",
                    "It closed at 23,270.6."])
    seen = []
    reviews = iter([
        {"checked": True, "blocked": True, "scores": {}, "unsupported": [{"claim": "x"}],
         "problems": ["These sentences are not supported by DATA: \"Volatility has been high all month.\""],
         "reason": "withheld"},
        {"checked": True, "blocked": False, "scores": {}, "unsupported": [], "problems": [], "reason": "clean"},
    ])
    monkeypatch.setattr(assistant, "chat", lambda messages: seen.append(messages) or next(replies))
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: next(reviews))
    r = assistant._answer("what now?", DATA)
    assert r["ok"] is True and "Volatility" not in r["answer"]
    assert "not supported by DATA" in seen[-1][-1]["content"]


def test_invented_numbers_short_circuit_the_paid_check(monkeypatch):
    # A draft that is being rewritten anyway should not also be billed to Jev.
    calls = []
    monkeypatch.setattr(assistant, "chat", lambda messages: "NIFTY will hit 24,500.")
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: calls.append(1) or {})
    assistant._answer("what next?", DATA)
    assert calls == []


# --- router -------------------------------------------------------------------

def _route(**probs):
    return _Resp(200, {"answers": {"route": {"type": "choice", "confidence": 0.9,
                                             "choice": max(probs, key=probs.get), "probabilities": probs}}})


def test_off_topic_question_is_refused_without_calling_the_model(jev_key, monkeypatch):
    monkeypatch.setattr(router, "jev", jev)
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _route(
        today=0.02, pattern_record=0.02, method=0.02, off_topic=0.94))
    monkeypatch.setattr(assistant, "chat", lambda messages: pytest.fail("the model should not be called"))
    r = assistant.ask("write me a poem")
    assert r["ok"] and r["answer"] == router.DECLINE and r["route"]["off_topic"]


def test_an_unsure_classification_still_goes_to_the_model(jev_key, monkeypatch):
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _route(
        today=0.4, pattern_record=0.05, method=0.05, off_topic=0.5))
    assert router.route("is anything close?")["off_topic"] is False


def test_router_failure_falls_through_to_the_model(monkeypatch):
    monkeypatch.setattr(jev, "_env", lambda k: None)
    r = router.route("why no trade?")
    assert r["checked"] is False and r["off_topic"] is False


def test_asking_for_advice_is_still_a_question_about_the_dashboard(jev_key, monkeypatch):
    # It gets answered (and then guarded), not turned away as off topic.
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _route(
        today=0.82, pattern_record=0.1, method=0.05, off_topic=0.03))
    assert router.route("should I buy a call today?")["off_topic"] is False


def test_empty_content_from_a_reasoning_model_is_a_clear_error(env, monkeypatch):
    # Gemini 3.x spends tokens thinking first; too small a budget returns a
    # message with no content at all rather than an error status.
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Resp(
        200, {"choices": [{"finish_reason": "length", "message": {"role": "assistant"}}]}))
    with pytest.raises(llm.LLMError, match="no text"):
        llm.chat([{"role": "user", "content": "hi"}])


# --- grades, drafts and the log ----------------------------------------------

import storage.copilot_log_db as log_db


def _review(blocked=False, honesty=1.0, clarity=1.0, problems=()):
    return {"checked": True, "blocked": blocked, "scores": {}, "unsupported": [],
            "problems": list(problems), "grades": {"honesty": honesty, "clarity": clarity},
            "reason": "withheld" if problems else "clean"}


def test_the_better_graded_of_two_clean_drafts_is_the_one_shown(monkeypatch):
    monkeypatch.setattr(assistant, "chat", lambda messages: "It closed at 23,270.6." if len(messages) == 2 else "x")
    texts = iter(["Dry but correct.", "Clear and honest."])
    monkeypatch.setattr(assistant, "chat", lambda messages: next(texts))
    grades = {"Dry but correct.": _review(honesty=1.0, clarity=0.5),
              "Clear and honest.": _review(honesty=2.0, clarity=1.8)}
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: grades[text])
    r = assistant._answer("explain", DATA, drafts=2)
    assert r["ok"] and r["answer"] == "Clear and honest." and r["drafts"] == 2
    assert r["grades"] == {"honesty": 2.0, "clarity": 1.8}


def test_a_low_grade_never_withholds_an_answer(monkeypatch):
    # Grades are recorded, not enforced. Only the guards block.
    monkeypatch.setattr(assistant, "chat", lambda messages: "Terse.")
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: _review(honesty=0.0, clarity=0.0))
    r = assistant._answer("explain", DATA)
    assert r["ok"] is True and r["grades"] == {"honesty": 0.0, "clarity": 0.0}


def test_a_clean_draft_beats_a_better_graded_blocked_one(monkeypatch):
    texts = iter(["Beautifully written forecast.", "Plain and clean."])
    monkeypatch.setattr(assistant, "chat", lambda messages: next(texts))
    grades = {"Beautifully written forecast.": _review(blocked=True, honesty=2.0, clarity=2.0,
                                                       problems=["This answer predicts the market."]),
              "Plain and clean.": _review(honesty=0.5, clarity=0.5)}
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: grades[text])
    r = assistant._answer("explain", DATA, drafts=2)
    assert r["ok"] is True and r["answer"] == "Plain and clean."


def test_every_answer_is_recorded_shown_or_withheld(monkeypatch):
    monkeypatch.setattr(assistant, "chat", lambda messages: "It closed at 23,270.6.")
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: _review())
    assistant._answer("why no trade?", DATA, kind="ask", route="today")

    monkeypatch.setattr(assistant, "chat", lambda messages: "NIFTY will hit 24,500.")
    assistant._answer("target?", DATA, kind="ask", route="today")

    rows = log_db.recent()
    assert [r["outcome"] for r in rows] == ["withheld", "shown"]
    assert rows[0]["bad_numbers"] == [24500.0] and rows[0]["question"] == "target?"
    assert rows[1]["grades"] == {"honesty": 1.0, "clarity": 1.0} and rows[1]["route"] == "today"


def test_an_off_topic_refusal_is_logged_as_declined_not_shown(jev_key, monkeypatch):
    # No model wrote it, so it is not evidence about the guards or the prose.
    monkeypatch.setattr(jev.requests, "post", lambda *a, **k: _route(
        today=0.01, pattern_record=0.0, method=0.0, off_topic=0.99))
    monkeypatch.setattr(assistant, "chat", lambda messages: pytest.fail("no model call expected"))
    assistant.ask("write me a poem")
    row = log_db.recent()[0]
    assert row["outcome"] == "declined" and row["drafts"] == 0


def test_a_broken_log_never_costs_the_user_their_answer(monkeypatch):
    def boom(*a, **k):
        raise sqlite_error()

    def sqlite_error():
        import sqlite3
        return sqlite3.OperationalError("disk full")

    monkeypatch.setattr(assistant, "record_answer", boom)
    monkeypatch.setattr(assistant, "chat", lambda messages: "It closed at 23,270.6.")
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: _review())
    assert assistant._answer("why?", DATA)["ok"] is True


def test_the_summary_surfaces_withheld_answers_as_candidate_cases():
    log_db.record({"kind": "ask", "question": "will it rise?", "outcome": "withheld", "drafts": 2,
                   "reason": "Answer withheld: it predicts where the market is going.",
                   "unsupported": [{"claim": "it should bounce"}]})
    log_db.record({"kind": "explain", "question": "explain", "outcome": "shown", "drafts": 2,
                   "grades": {"honesty": 2.0, "clarity": 1.5}})
    s = log_db.summary()
    assert s["answers"] == 2 and s["shown"] == 1 and s["withheld"] == 1
    assert s["grades"] == {"honesty": 2.0, "clarity": 1.5}
    assert s["flagged_for_review"][0]["unsupported"] == ["it should bounce"]
    assert s["needed_a_retry"] == 1


# --- the deterministic explainer, shadowed and as a fallback ------------------

@pytest.fixture
def explain_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(assistant, "CACHE_PATH", tmp_path / "explain.json")
    monkeypatch.setattr(assistant, "build_context", lambda symbol, live=None, scope=None: DATA)
    monkeypatch.setattr(assistant, "compose", lambda data: "Composed: it closed at 23,270.6.")
    monkeypatch.setattr(assistant, "review_answer", lambda text, data: _review(honesty=2.0, clarity=1.4))


def test_the_composed_version_runs_beside_the_model_and_is_logged_not_shown(explain_setup, monkeypatch):
    monkeypatch.setattr(assistant, "chat", lambda messages: "Model: it closed at 23,270.6.")
    r = assistant.explain_today()
    assert r["ok"] and r["answer"].startswith("Model:") and r["method"] == "gemini"
    rows = {row["method"]: row for row in log_db.recent()}
    assert rows["composed"]["outcome"] == "shadow"
    assert rows["composed"]["grades"] == {"honesty": 2.0, "clarity": 1.4}
    assert rows["gemini"]["outcome"] == "shown"


def test_a_provider_outage_serves_the_composed_explanation_instead_of_an_error(explain_setup, monkeypatch):
    # The composed text is assembled from the same computed data and cannot
    # invent anything, so serving it beats serving a 502.
    def down(messages):
        raise assistant.LLMError("gemini returned HTTP 503")

    monkeypatch.setattr(assistant, "chat", down)
    r = assistant.explain_today()
    assert r["ok"] and r["answer"].startswith("Composed:") and r["method"] == "composed"
    assert "unavailable" in r["fallback_from"]
    assert log_db.recent()[0]["outcome"] == "shown" and log_db.recent()[0]["method"] == "composed"


def test_a_blocked_composed_answer_is_never_served_as_the_fallback(explain_setup, monkeypatch):
    # Should never happen — every number in it came from the data — so if it
    # does, the error is the right outcome, not a quietly withheld answer.
    monkeypatch.setattr(assistant, "review_answer",
                        lambda text, data: _review(blocked=True, problems=["unsupported"]))
    monkeypatch.setattr(assistant, "chat", lambda messages: (_ for _ in ()).throw(assistant.LLMError("down")))
    with pytest.raises(assistant.LLMError):
        assistant.explain_today()


def test_the_composed_answer_goes_through_the_same_guards(explain_setup, monkeypatch):
    seen = []
    monkeypatch.setattr(assistant, "review_answer",
                        lambda text, data: seen.append(text) or _review())
    monkeypatch.setattr(assistant, "chat", lambda messages: "Model: it closed at 23,270.6.")
    assistant.explain_today()
    assert any(t.startswith("Composed:") for t in seen)


def test_a_transient_outage_does_not_become_the_whole_days_explanation(explain_setup, monkeypatch):
    # Found live: a 503 served the composed version, which was then cached,
    # so the model would not have been retried until tomorrow.
    calls = []

    def flaky(messages):
        calls.append(1)
        if len(calls) == 1:
            raise assistant.LLMError("gemini returned HTTP 503")
        return "Model: it closed at 23,270.6."

    monkeypatch.setattr(assistant, "chat", flaky)
    first = assistant.explain_today()
    assert first["method"] == "composed" and not first["cached"]
    second = assistant.explain_today()
    assert second["method"] == "gemini" and not second["cached"]
    assert assistant.explain_today()["cached"] is True
