"""Today's trade recommendation — calls, puts, or nothing.

Two rules govern this, and they're the reason it will usually say NO TRADE:

1. A strategy only gets recommended if its own historical expectancy is
   positive. Most tested strategies aren't, so most don't qualify.
2. Even a positive index edge has to survive being expressed as an option.
   The strike sweep measures that separately, because a signal can be
   genuinely profitable on the index and still lose money as a bought
   option once theta and spreads are paid.

Saying "no trade" when nothing clears those bars is the system working,
not failing. Manufacturing a recommendation to fill the space is the
failure mode this is built to avoid.
"""

from backtest.hypothesis_log import total_hypotheses_tested
from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from stats.multiple_comparisons import required_bar

# Base bar before any multiple-comparisons adjustment. Index round-trip
# costs are ~0.2% and option costs far more, so an expectancy of a few
# thousandths of a percent is indistinguishable from noise even before
# accounting for how many strategies have been tried against the same
# data. The actual bar used is scaled up from these by required_bar()
# below, based on the running hypothesis count.
BASE_MIN_EXPECTANCY_PCT = 0.25
BASE_MIN_TRADES = 30


def _firing_today(symbol: str, days: int = 800) -> tuple[list[dict], str, str]:
    df, regime_series = load_daily_data(symbol, days)
    as_of = str(df.index[-1].date())
    regime = str(regime_series.iloc[-1])

    firing = []
    for name, spec in STRATEGY_REGISTRY.items():
        entries = spec["fn"](df, regime_series, **spec["params"])
        if bool(entries.iloc[-1]):
            firing.append({
                "strategy": name,
                "label": spec.get("label", name),
                "direction": spec.get("direction", "long"),
                "option_type": spec.get("option_type", "CE"),
            })
    return firing, as_of, regime


def build_recommendation(symbol: str = "^NSEI", days: int = 3200) -> dict:
    from backtest.research import run_all_strategies

    firing, as_of, regime = _firing_today(symbol)
    track_record = run_all_strategies(symbol=symbol, days=7000)["results"]

    bar = required_bar(
        num_hypotheses_tested=total_hypotheses_tested(),
        base_expectancy_pct=BASE_MIN_EXPECTANCY_PCT,
        base_trades=BASE_MIN_TRADES,
    )

    candidates = []
    for f in firing:
        rec = track_record.get(f["strategy"], {})
        expectancy = rec.get("expectancy_pct")
        trades = rec.get("num_trades") or 0
        qualifies = (expectancy or 0) >= bar.min_expectancy_pct and trades >= bar.min_trades
        if qualifies:
            why_not = None
        elif (expectancy or 0) < bar.min_expectancy_pct:
            why_not = f"expectancy {expectancy}% is below the {bar.min_expectancy_pct}% bar"
        else:
            why_not = f"only {trades} trades, below the {bar.min_trades}-trade bar"
        candidates.append({
            **f,
            "index_expectancy_pct": expectancy,
            "index_trades": trades,
            "qualifies": qualifies,
            "why_not": why_not,
        })

    qualified = [c for c in candidates if c["qualifies"]]
    qualified.sort(key=lambda c: c["index_expectancy_pct"] or 0, reverse=True)

    bar_info = {
        "min_expectancy_pct": bar.min_expectancy_pct,
        "min_trades": bar.min_trades,
        "num_hypotheses_tested": bar.num_hypotheses_tested,
        "scale_factor": bar.scale_factor,
        "methodology_note": bar.methodology_note,
    }

    if not firing:
        return {
            "as_of": as_of,
            "regime": regime,
            "action": "NO_TRADE",
            "headline": "No setup today.",
            "reason": (
                f"None of the {len(STRATEGY_REGISTRY)} tested strategies is signalling on the latest "
                f"close. The market is {regime}; waiting is the position."
            ),
            "candidates": [],
            "warnings": [],
            "evidence_bar": bar_info,
        }

    if not qualified:
        detail = "; ".join(f"{c['label']} — {c['why_not']}" for c in candidates)
        return {
            "as_of": as_of,
            "regime": regime,
            "action": "NO_TRADE",
            "headline": "Setups are firing, but none clears the evidence bar.",
            "reason": (
                f"Signalling today: {detail}. A signal firing is not the same as a signal worth "
                f"trading — each must show at least {bar.min_expectancy_pct}% historical expectancy "
                f"over {bar.min_trades}+ trades before it earns a recommendation (this bar is scaled "
                f"up from a {BASE_MIN_EXPECTANCY_PCT}%/{BASE_MIN_TRADES}-trade base by "
                f"{bar.scale_factor}x, reflecting the {bar.num_hypotheses_tested} hypotheses tested "
                "against this data so far)."
            ),
            "candidates": candidates,
            "warnings": [],
            "evidence_bar": bar_info,
        }

    best = qualified[0]
    is_call = best["option_type"] == "CE"
    return {
        "as_of": as_of,
        "regime": regime,
        "action": "CONSIDER_CALL" if is_call else "CONSIDER_PUT",
        "headline": f"{best['label']} is signalling — a {'CALL' if is_call else 'PUT'} setup.",
        "reason": (
            f"{best['label']} fired on the {as_of} close in a {regime} market. Its historical index "
            f"expectancy is {best['index_expectancy_pct']}% over {best['index_trades']} trades."
        ),
        "candidates": candidates,
        "warnings": [
            "Historical index expectancy is not option expectancy. The strike sweep measures what "
            "buying the option actually returned after theta and spreads — check it before acting.",
            "No strategy here is APPROVED; the best is CONDITIONAL. Treat this as an idea to "
            "evaluate, not an instruction.",
        ],
        "evidence_bar": bar_info,
    }
