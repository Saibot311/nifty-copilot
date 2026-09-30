"""The pipeline's two straddles beside the patterns in the Today call: listed
when their condition holds on the last close, held to the same gate, and
never the call itself."""

import math
from datetime import date, timedelta

import briefing.pipeline_candidates as pc

STUDY = {"hypotheses": [
    {"name": "event_straddle", "verdict": "REJECTED", "reason": "lost", "holdout": {"t_vs_baseline": 0.32, "num_trades": 21,
                                                                                   "mean_pct": -3.2}},
    {"name": "cheap_vol_straddle", "verdict": "REJECTED", "reason": "lost", "holdout": {"t_vs_baseline": -0.67,
                                                                                       "num_trades": 49, "mean_pct": -9.3}}]}


def closes(last: date, daily_move: float) -> dict:
    """22 closes alternating up and down by `daily_move`: realised vol = move x sqrt(252)."""
    return {last - timedelta(days=21 - k): 20000 * math.exp(daily_move * (k % 2)) for k in range(22)}


def test_the_close_before_a_scheduled_decision_lists_the_event_straddle():
    c = pc.straddle_candidates("2026-10-06", 65, closes(date(2026, 10, 6), 0.001), 0.5, STUDY)
    assert [x["strategy"] for x in c] == ["event_straddle"]
    assert c[0]["label"] == "Event straddle (RBI policy decision on 7 Oct)"
    assert c[0]["why_not"] == "option verdict REJECTED" and not c[0]["qualifies"]


def test_the_next_session_skips_the_weekend_and_off_cycle_decisions_do_not_count():
    assert pc.next_weekday(date(2025, 1, 31)).isoformat() == "2025-02-03"
    ev = pc.events()
    assert "2020-03-27" not in ev and ev["2019-07-05"] == "Union Budget" and ev["2026-12-04"] == "RBI policy decision"


def test_cheap_volatility_is_implied_below_the_last_21_sessions_realised():
    from backtest.nifty_pipeline import realised_vol
    series = closes(date(2026, 9, 30), 0.01)
    rv = realised_vol([series[d] for d in sorted(series)])
    below = pc.straddle_candidates("2026-09-30", 65, series, rv - 0.01, STUDY)
    above = pc.straddle_candidates("2026-09-30", 65, series, rv + 0.01, STUDY)
    assert [x["strategy"] for x in below] == ["cheap_vol_straddle"] and above == []
    assert pc.straddle_candidates("2026-09-30", 65, series, None, STUDY) == []


def test_even_an_approved_straddle_is_never_the_call():
    approved = {"hypotheses": [{"name": "event_straddle", "verdict": "APPROVED", "reason": "r",
                                "holdout": {"t_vs_baseline": 9.0, "num_trades": 40, "mean_pct": 12.0}}]}
    [c] = pc.straddle_candidates("2026-10-06", 65, closes(date(2026, 10, 6), 0.001), 0.5, approved)
    assert not c["qualifies"] and "forward log records only a call or a put" in c["why_not"]


def test_the_call_lists_them_and_stays_no_trade(monkeypatch):
    import briefing.recommendation as rec_mod
    prox = {"as_of": "2026-10-06", "regime": "RANGE", "patterns": []}
    monkeypatch.setattr(rec_mod, "cached", lambda key, ttl_seconds, producer: prox)
    monkeypatch.setattr(rec_mod, "load_research", lambda: {"patterns": []})
    monkeypatch.setattr(rec_mod, "holdout_family", lambda r: {"patterns": 0, "iv_filter": 1, "structural": 6,
                                                               "replication": 22, "news_tone": 5, "total": 65})
    monkeypatch.setattr(rec_mod, "_pipeline_candidates", lambda as_of, tests: pc.straddle_candidates(
        as_of, tests, closes(date(2026, 10, 6), 0.001), 0.5, STUDY))
    r = rec_mod.build_recommendation()
    assert r["action"] == "NO_TRADE" and r["headline"] == "Setups formed, but none has a proven option edge."
    assert "Event straddle (RBI policy decision on 7 Oct) (option verdict REJECTED)" in r["reason"]
