"""The facts the copilot is allowed to talk about: a compact digest of what
the system has already computed. Every number in it comes from deterministic
code — the guard checks answers against exactly this.

Which facts depends on what was asked. router.py classifies the question
first, and `scope` selects the view it needs:

  today           the dashboard as it stands: what formed, what could form
                  next, the live gap, the analog test. The default.
  pattern_record  every researched pattern's option record, all 26 of them,
                  not just the ones near firing today.
  method          how the system decides: its rules, the evidence bar, the
                  analog test's own verdict. No pattern lists, no live data.
  market          how the market itself works: the market context engine's
                  reading of today, its studies, and the sourced principles.

The point is not smaller prompts. A question the context cannot answer gets
answered anyway, from whatever happens to be in it — asked which pattern had
the best option record, the copilot named one that lost ₹1,170 per lot,
because the three better ones were not formed that day and so were not
there. Every figure it gave was real. The answer was still wrong.

Kept small enough to fit free-tier per-minute token limits either way.
"""

from backtest.iv_research import load_iv_research
from backtest.pattern_options import LOT_SIZE, load_research
from backtest.pattern_proximity import pattern_proximity
from backtest.similarity import run_similarity
from briefing.forward_log import forward_report
from briefing.recommendation import build_recommendation
from cache import cached

# What each scope carries on top of the core. "today" and the default are
# the same thing: the daily explanation needs the whole dashboard, and
# there is no honest saving to make there.
SCOPES = {
    "today": ("patterns", "live", "similarity", "forward"),
    "pattern_record": ("patterns", "all_records", "forward"),
    "method": ("similarity", "forward"),
    "market": ("market", "forward"),
}
DEFAULT_SECTIONS = SCOPES["today"]

HOW_IT_DECIDES = {
    "verdicts": {
        "APPROVED": "Beat a direction-matched baseline on data it never saw, by more than the evidence bar.",
        "CONDITIONAL": "Beat the baseline on unseen data by more than luck would explain, but on too few "
                       "trades to trust yet.",
        "REJECTED": "No proven edge: lost money, did no better than the baseline, or did better by an "
                    "amount luck could explain.",
    },
    "development_and_holdout": "Every pattern's option setup is chosen on data up to the end of 2023 (the "
                               "development period) and then judged once on 2024 onward (the holdout), which it "
                               "never saw. Judging on the data a choice was made from is how backtests flatter "
                               "themselves.",
    "direction_matched_baseline": "A result is compared against buying the same kind of option on days with no "
                                  "signal at all, so a rising market does not get mistaken for a working pattern.",
    "execution_rule": "A signal on today's close is never acted on at that same close. Index results enter at "
                      "the next session's open; option results enter at the next session's close, because the "
                      "option archive records one reliable price a day.",
    "evidence_bar": "The t-statistic a result must clear, raised as more patterns are tested so that "
                    "testing many does not make one look good by chance.",
    "t_stat": "How far a result is from what luck would produce. The bar is about 2 for a large sample and "
              "higher for a small one, because a few trades can look good by chance.",
    "provisional": "The day has not closed yet, so the figure can still change.",
    "what_it_will_not_do": "It does not predict prices and does not tell you to trade.",
}


def _option_record(r: dict) -> dict | None:
    h = r.get("holdout") or {}
    if not r.get("suggested_option"):
        return None
    return {
        "option": r["suggested_option"]["description"],
        "verdict": r.get("status"),
        "trades_2024_26": h.get("num_trades"),
        "win_rate": h.get("win_rate"),
        "avg_profit_per_lot_rs": h.get("avg_profit_per_lot_rs"),
        "no_signal_avg_rs": (r.get("baseline") or {}).get("holdout_avg_profit_per_lot_rs"),
        "t_stat": r.get("holdout_t_stat"),
    }


def _all_records(research: dict) -> list[dict]:
    """Every researched pattern, best measured record first. Patterns with
    no holdout record are kept and marked, not dropped: "it has not been
    measured" is a different answer from "it did badly"."""
    rows = []
    for r in research.values():
        rec = _option_record(r)
        rows.append({
            "name": r.get("label"),
            "option_type": "CALL" if r.get("option_type") == "CE" else "PUT",
            "forms_per_year": r.get("forms_per_year"),
            "option_record": rec,
            "measured": bool(rec and rec.get("avg_profit_per_lot_rs") is not None),
        })
    return sorted(
        rows,
        key=lambda x: (x["measured"], (x["option_record"] or {}).get("avg_profit_per_lot_rs") or 0),
        reverse=True,
    )


def _market_digest() -> dict:
    """The engine's reading and the research behind it, trimmed to what an
    answer can use. Imported here, not at the top: it is only loaded when a
    question is about the market itself."""
    from market_engine.engine import load_studies, today
    from market_engine.knowledge import KNOWLEDGE

    t = cached("market_today", ttl_seconds=1800, producer=today)
    s = load_studies() or {}
    vrp = s.get("variance_risk_premium") or {}
    pos = t.get("positioning") or {}
    return {
        "why_the_latest_session_moved": {k: v for k, v in (t.get("why_it_moved") or {}).items() if k != "note"},
        "options_price_now": t.get("options_price_now"),
        "expiry": t.get("expiry"),
        "unusual_strike_activity": (t.get("unusual_strike_activity") or {}).get("unusual"),
        "positioning": {"date": pos.get("date"), "by_participant": pos.get("by_participant")},
        "variance_risk_premium": {k: vrp.get(k) for k in ("days", "period", "avg_implied", "avg_delivered",
                                                          "median_gap_points", "options_overpriced_share",
                                                          "when_sellers_were_hurt")},
        "option_buyers_without_a_signal": s.get("option_buyers_without_a_signal"),
        "global_cues_by_year": s.get("global_cues_by_year"),
        "expiry_footprints": {k: (s.get("expiry_footprints") or {}).get(k)
                              for k in ("all", "jan_2023_to_mar_2025", "caveat")},
        "positioning_history": s.get("positioning_history"),
        "sebi_studies": s.get("sebi"),
        "principles": [{k: p[k] for k in ("title", "principle", "for_you", "sources")} for p in KNOWLEDGE],
    }


def build_context(symbol: str = "^NSEI", live: dict | None = None, scope: str | None = None) -> dict:
    sections = SCOPES.get(scope or "", DEFAULT_SECTIONS)
    rec = cached(f"recommendation:{symbol}", ttl_seconds=600, producer=lambda: build_recommendation(symbol))
    prox = cached(f"proximity:{symbol}", ttl_seconds=1800, producer=lambda: pattern_proximity(symbol))
    research = {p["strategy"]: p for p in (load_research() or {}).get("patterns", [])}

    def pattern(p: dict) -> dict:
        return {
            "name": p["label"],
            "option_type": "CALL" if p["option_type"] == "CE" else "PUT",
            "forms_when": p.get("forms_when"),
            "idea": p.get("why"),
            "forms_on_close_between": (p.get("trigger") or {}).get("close_ranges_level"),
            "share_of_recent_days_like_that": p.get("probability_next"),
            "option_record": _option_record(research.get(p["strategy"], {})),
        }

    ctx = {
        "fixed_facts": {"market_close_ist": "15:30", "lot_size": LOT_SIZE, "option_evidence_period": "2024-2026"},
        "as_of_close": prox["as_of"],
        "last_close": prox["last_close"],
        "regime": prox["regime"],
        "recommendation": {
            "action": rec["action"], "headline": rec["headline"], "reason": rec["reason"],
            "bar": {"min_t": rec["evidence_bar"]["min_t"], "patterns_judged": rec["evidence_bar"]["patterns_judged"]},
        },
        "how_it_decides": HOW_IT_DECIDES,
    }
    iv = load_iv_research()
    if iv:
        latest = iv["series"]["latest"]
        ctx["implied_volatility"] = {
            "as_of": latest["date"],
            "iv_30d_pct": latest["iv_30d_pct"],
            "percentile_1y": latest["percentile_1y"],
            "tested_as_filter": iv["preregistered_test"]["verdict"],
            "what_it_means": "What options cost: higher implied volatility means paying more for the same "
                             "expected move. Context about price, not a signal about direction.",
        }

    if "patterns" in sections:
        ctx["patterns_formed_on_last_close"] = [pattern(p) for p in prox["patterns"] if p.get("formed_today")]
        ctx["patterns_that_could_form_next_close"] = [
            pattern(p) for p in prox["patterns"]
            if not p.get("formed_today") and (p.get("probability_next") or 0) >= 0.02
        ]
    if "all_records" in sections:
        ctx["every_pattern_researched"] = _all_records(research)
    if "similarity" in sections:
        # Only computed when the scope needs it — a question about a
        # pattern's record should not wait for the analog search.
        sim = cached(f"similarity:{symbol}", ttl_seconds=1800, producer=lambda: run_similarity(symbol))
        wf = sim.get("walk_forward", {})
        ctx["similar_past_days"] = {
            "count": len(sim.get("analogs", [])),
            "after_5_days": sim.get("outcomes", {}).get("analogs", {}).get("5d"),
            "all_days_after_5_days": sim.get("outcomes", {}).get("all_days", {}).get("5d"),
            "predictive_test": {"correlation": wf.get("rank_correlation"), "t": wf.get("t_stat"),
                                "direction_right_pct": wf.get("direction_hit_rate"), "verdict": wf.get("verdict")},
        }
    if "forward" in sections:
        ctx["forward_track_record"] = forward_report(symbol)["summary"]
    if "market" in sections:
        ctx["market"] = _market_digest()
    if "live" in sections and live and live.get("candle"):
        ctx["live_now"] = {
            "provisional_until_close": live.get("provisional"),
            "basis": live.get("basis"),
            "price_now": live["candle"]["close"],
            "change_pct": live.get("change_pct"),
            "would_form_if_closed_now": [p["label"] for p in live.get("patterns", []) if p.get("would_form_now")],
            "near_trigger": [
                {"name": p["label"], "points_away": p["points_to_trigger"], "pct_away": p["pct_to_trigger"]}
                for p in live.get("patterns", []) if not p.get("would_form_now")
            ],
        }
    return ctx
