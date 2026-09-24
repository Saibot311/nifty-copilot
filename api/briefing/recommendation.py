"""Today's call — CALL, PUT or NO TRADE — from the patterns that formed on the
last final close and what the option each points to has actually made.

A pattern earns a recommendation only if all of these hold:
  1. It formed on the last *final* daily close (never a still-forming bar).
  2. Its option verdict (backtest/pattern_options.py) is APPROVED: profitable
     per lot on 2024-26 data its option was never chosen on, and better than
     buying that same option with no signal.
  3. Its holdout t-statistic clears a Bonferroni threshold across every
     pattern judged on the holdout (I5). Twenty-six patterns each get one shot
     at the holdout, so one of them clearing t = 2 by luck alone is likely;
     the bar rises with that count — and with how few trades the verdict
     rests on, since it is Student's t at the pattern's own degrees of freedom.

Expect NO TRADE most days. Manufacturing a call to fill the space is the
failure this is built to avoid.
"""

from backtest.pattern_options import load_research
from backtest.pattern_proximity import pattern_proximity
from backtest.family import holdout_family
from cache import cached
from stats.multiple_comparisons import FAMILY_ALPHA, required_t


def _now():
    from datetime import datetime

    from market_data.live_quote import IST
    return datetime.now(IST)


def _next_close_phrase(as_of: str) -> str:
    """Which close "could form" refers to. After 15:30 on a weekday whose own
    close is not in the data yet (NSE's file arrives with the evening job),
    the next close in the data is today's — already over, just not recorded."""
    now = _now()
    if now.weekday() < 5 and (now.hour, now.minute) >= (15, 30) and as_of < now.date().isoformat():
        return "today's close (already over, not in the data yet — the evening job records it)"
    return "the next close"


def build_recommendation(symbol: str = "^NSEI") -> dict:
    prox = cached(f"proximity:{symbol}", ttl_seconds=1800, producer=lambda: pattern_proximity(symbol))
    research = load_research()
    by_name = {p["strategy"]: p for p in (research or {}).get("patterns", [])}
    # The bar is corrected for every hypothesis that has had its look at the
    # holdout, not just the patterns: the IV filter, the structural tests, the
    # replications and the news-tone tests took theirs too, and each one was
    # another chance for luck to clear it.
    family = holdout_family(research)
    judged, tests = family["patterns"], family["total"]
    # The large-sample bar: the lowest it can be. Each candidate is held to
    # the bar for its own sample size, which is higher.
    min_t = required_t(tests)

    base = {"as_of": prox["as_of"], "regime": prox["regime"]}
    bar = {
        "min_t": min_t,
        "patterns_judged": judged,
        "tests_judged": tests,
        "family": {k: v for k, v in family.items() if k != "total"},
        "methodology_note": (
            f"{tests} hypotheses have each been judged once on 2024-26 option data — {judged} patterns, "
            f"{family['structural']} structural tests, {family['replication']} replications on other indices, "
            f"{family['news_tone']} news-tone tests and {family['iv_filter']} implied-volatility filter. To keep the chance of any "
            f"false recommendation across all of them near {FAMILY_ALPHA:.0%}, a pattern needs APPROVED and "
            f"a holdout t of at least {min_t} (Bonferroni) — more when it rests on few trades, because the "
            "bar is Student's t at the pattern's own degrees of freedom."
        ),
    }

    if research is None:
        return {**base, "action": "NO_TRADE", "headline": "Option research hasn't been computed.",
                "reason": "Run scripts/pattern_options.py — without it there's no evidence to recommend from.",
                "candidates": [], "warnings": [], "evidence_bar": bar}

    candidates = []
    for p in prox["patterns"]:
        if not p.get("formed_today"):
            continue
        r = by_name.get(p["strategy"], {})
        t = r.get("holdout_t_stat")
        n = (r.get("holdout") or {}).get("num_trades", 0)
        own_bar = required_t(tests, df=n - 1) if n >= 2 else None
        status = r.get("status", "REJECTED")
        if status != "APPROVED":
            why_not = f"option verdict {status}"
        elif t is None or own_bar is None or t < own_bar:
            why_not = f"APPROVED, but t {t} is below the {own_bar} bar for {n} holdout trades"
        else:
            why_not = None
        candidates.append({
            "strategy": p["strategy"], "label": p["label"], "direction": p["direction"],
            "option_type": p["option_type"], "status": status, "verdict_reason": r.get("reason"),
            "suggested_option": (r.get("suggested_option") or {}).get("description"),
            "holdout_trades": (r.get("holdout") or {}).get("num_trades", 0),
            "holdout_avg_profit_per_lot_rs": (r.get("holdout") or {}).get("avg_profit_per_lot_rs"),
            "holdout_t_stat": t, "required_t": own_bar, "qualifies": why_not is None, "why_not": why_not,
        })

    close_txt = f"the {prox['as_of']} close"
    if not candidates:
        could = [p["label"] for p in prox["patterns"] if (p.get("probability_next") or 0) >= 0.02]
        return {**base, "action": "NO_TRADE", "headline": "No pattern formed on the last close.",
                "reason": (f"None of the {len(prox['patterns'])} patterns formed on {close_txt}. "
                           + (f"Could form on {_next_close_phrase(prox['as_of'])}: {', '.join(could)} — see Patterns."
                              if could else "")),
                "candidates": [], "warnings": [], "evidence_bar": bar}

    qualified = [c for c in candidates if c["qualifies"]]
    if not qualified:
        detail = "; ".join(f"{c['label']} ({c['why_not']})" for c in candidates)
        return {**base, "action": "NO_TRADE", "headline": "Patterns formed, but none has a proven option edge.",
                "reason": f"Formed on {close_txt}: {detail}.", "candidates": candidates, "warnings": [],
                "evidence_bar": bar}

    if len({c["option_type"] for c in qualified}) > 1:
        return {**base, "action": "NO_TRADE", "headline": "Proven call and put setups formed together.",
                "reason": "Qualifying patterns point in opposite directions on the same close; standing aside.",
                "candidates": candidates, "warnings": [], "evidence_bar": bar}

    best = max(qualified, key=lambda c: c["holdout_avg_profit_per_lot_rs"] or 0)
    is_call = best["option_type"] == "CE"
    return {
        **base,
        "action": "CONSIDER_CALL" if is_call else "CONSIDER_PUT",
        "headline": f"{best['label']} formed — {best['suggested_option']}.",
        "reason": (
            f"{best['label']} formed on {close_txt} in a {prox['regime']} market. On 2024-26 data its option "
            f"averaged ₹{best['holdout_avg_profit_per_lot_rs']:,} per lot over {best['holdout_trades']} trades "
            f"(t = {best['holdout_t_stat']})."
        ),
        "candidates": candidates,
        "warnings": [
            "Entry assumes buying at the next session's close price, as in the backtest. Check the live premium "
            "and spread before acting; a much worse fill changes the result.",
            "Past profit on unseen data is evidence, not a promise. Size so a full loss of the premium is affordable.",
        ],
        "evidence_bar": bar,
    }
