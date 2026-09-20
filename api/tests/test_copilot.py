"""Phase 12 copilot. The guard is the point: the LLM may explain numbers the
system computed, never introduce its own. Tests never call a real provider."""

import pytest

import copilot.assistant as assistant
import copilot.llm_client as llm
from copilot.guard import numbers_in_text, unverified_numbers

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
    assert r["ok"] is False and r["answer"] is None and "24800" in r["reason"]


def test_retry_that_fixes_the_numbers_is_shown(monkeypatch):
    replies = iter(["NIFTY will hit 24,500.", "The system gives no target; it closed at 23,270.6."])
    monkeypatch.setattr(assistant, "chat", lambda messages: next(replies))
    r = assistant._answer("what next?", DATA)
    assert r["ok"] is True and "23,270.6" in r["answer"]


def test_explanation_is_saved_per_day_and_not_regenerated(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(assistant, "CACHE_PATH", tmp_path / "explain.json")
    monkeypatch.setattr(assistant, "build_context", lambda symbol, live=None: DATA)
    monkeypatch.setattr(assistant, "chat", lambda messages: calls.append(1) or "It closed at 23,270.6.")
    first, second = assistant.explain_today(), assistant.explain_today()
    assert first["ok"] and not first["cached"] and second["cached"] and len(calls) == 1


def test_every_number_in_the_data_passes_its_own_check():
    # Found on real data: 3-decimal fractions (0.452) were rejected, which
    # would have withheld honest answers that quote the data verbatim.
    import json

    data = {**DATA, "probability": 0.452, "hit": 0.001, "levels": [[22572, 23154]]}
    assert unverified_numbers(json.dumps(data), data) == []


# --- prediction guard (TypeSafe Jev) -----------------------------------------

import copilot.prediction_guard as pg


def _jev(predicts: float, advises: float):
    return _Resp(200, {"model": "jev-1.13.0", "answers": {
        "predicts_market": {"type": "noul", "noul": predicts},
        "advises_trade": {"type": "noul", "noul": advises},
    }})


@pytest.fixture
def jev_key(monkeypatch):
    monkeypatch.setattr(pg, "_env", lambda k: "ts-key" if k == "TYPESAFE_API_KEY" else None)


def test_forecast_without_any_number_is_blocked(jev_key, monkeypatch):
    # The gap the number guard cannot cover: a prediction with no figures in it.
    monkeypatch.setattr(pg.requests, "post", lambda *a, **k: _jev(0.91, 0.04))
    r = pg.check("The setup looks set to push higher from here.")
    assert r["checked"] and r["blocked"] and "predicts" in r["reason"]


def test_explaining_the_systems_own_verdict_passes(jev_key, monkeypatch):
    monkeypatch.setattr(pg.requests, "post", lambda *a, **k: _jev(0.04, 0.02))
    r = pg.check("The system says NO_TRADE because no pattern formed.")
    assert r["checked"] and not r["blocked"]


def test_threshold_is_low_because_missing_a_forecast_is_the_costly_error(jev_key, monkeypatch):
    monkeypatch.setattr(pg.requests, "post", lambda *a, **k: _jev(0.35, 0.0))
    assert pg.check("Momentum may carry it up.")["blocked"] is True
    assert pg.BLOCK_ABOVE == 0.3


def test_questions_are_two_separate_nouls_in_one_request(jev_key, monkeypatch):
    sent = {}
    monkeypatch.setattr(pg.requests, "post", lambda url, **k: sent.update(k["json"]) or _jev(0.0, 0.0))
    pg.check("text")
    assert set(sent["questions"]) == {"predicts_market", "advises_trade"}
    assert all(q["type"] == "noul" for q in sent["questions"].values())
    assert sent["state"] == "text" and sent["model"] == "jev-latest"


def test_no_key_skips_the_check_instead_of_blocking(monkeypatch):
    monkeypatch.setattr(pg, "_env", lambda k: None)
    r = pg.check("anything")
    assert r["checked"] is False and r["blocked"] is False


def test_guard_outage_never_blocks_the_copilot(jev_key, monkeypatch):
    def boom(*a, **k):
        raise pg.requests.RequestException("down")
    monkeypatch.setattr(pg.requests, "post", boom)
    r = pg.check("anything")
    assert r["checked"] is False and r["blocked"] is False and "unavailable" in r["reason"]


def test_assistant_withholds_an_answer_the_prediction_guard_blocks(monkeypatch):
    monkeypatch.setattr(assistant, "chat", lambda messages: "Nothing formed, but it should bounce soon.")
    monkeypatch.setattr(assistant, "prediction_check",
                        lambda text: {"checked": True, "blocked": True, "scores": {"predicts_market": 0.8},
                                      "reason": "Answer withheld: it predicts where the market is going, which this tool must not do."})
    r = assistant._answer("what now?", DATA)
    assert r["ok"] is False and r["answer"] is None and "predicts" in r["reason"]


def test_empty_content_from_a_reasoning_model_is_a_clear_error(env, monkeypatch):
    # Gemini 3.x spends tokens thinking first; too small a budget returns a
    # message with no content at all rather than an error status.
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _Resp(
        200, {"choices": [{"finish_reason": "length", "message": {"role": "assistant"}}]}))
    with pytest.raises(llm.LLMError, match="no text"):
        llm.chat([{"role": "user", "content": "hi"}])
