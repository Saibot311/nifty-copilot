"""The facts the copilot is allowed to talk about: a compact digest of what
the system has already computed. Kept small (~2k tokens) so it fits free-
tier per-minute token limits, and every number in it is from deterministic
code — the guard checks answers against exactly this."""

from backtest.pattern_options import LOT_SIZE, load_research
from backtest.pattern_proximity import pattern_proximity
from backtest.similarity import run_similarity
from briefing.forward_log import forward_report
from briefing.recommendation import build_recommendation
from cache import cached


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


def build_context(symbol: str = "^NSEI", live: dict | None = None) -> dict:
    rec = cached(f"recommendation:{symbol}", ttl_seconds=600, producer=lambda: build_recommendation(symbol))
    prox = cached(f"proximity:{symbol}", ttl_seconds=1800, producer=lambda: pattern_proximity(symbol))
    sim = cached(f"similarity:{symbol}", ttl_seconds=1800, producer=lambda: run_similarity(symbol))
    research = {p["strategy"]: p for p in (load_research() or {}).get("patterns", [])}
    fwd = forward_report(symbol)["summary"]

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

    formed = [pattern(p) for p in prox["patterns"] if p.get("formed_today")]
    near = [pattern(p) for p in prox["patterns"] if not p.get("formed_today") and (p.get("probability_next") or 0) >= 0.02]
    wf = sim.get("walk_forward", {})

    ctx = {
        "fixed_facts": {"market_close_ist": "15:30", "lot_size": LOT_SIZE, "option_evidence_period": "2024-2026"},
        "as_of_close": prox["as_of"],
        "last_close": prox["last_close"],
        "regime": prox["regime"],
        "recommendation": {
            "action": rec["action"], "headline": rec["headline"], "reason": rec["reason"],
            "bar": {"min_t": rec["evidence_bar"]["min_t"], "patterns_judged": rec["evidence_bar"]["patterns_judged"]},
        },
        "patterns_formed_on_last_close": formed,
        "patterns_that_could_form_next_close": near,
        "similar_past_days": {
            "count": len(sim.get("analogs", [])),
            "after_5_days": sim.get("outcomes", {}).get("analogs", {}).get("5d"),
            "all_days_after_5_days": sim.get("outcomes", {}).get("all_days", {}).get("5d"),
            "predictive_test": {"correlation": wf.get("rank_correlation"), "t": wf.get("t_stat"),
                                "direction_right_pct": wf.get("direction_hit_rate"), "verdict": wf.get("verdict")},
        },
        "forward_track_record": fwd,
    }
    if live and live.get("candle"):
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
