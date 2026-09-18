"""Phase 7: run many strategies/parameter combinations against real
history and track every one of them. This is exploratory research, not
confirmatory testing — nothing here becomes "validated" just by running;
that word is reserved for Phase 8, after a strategy survives a hold-out
period it played no role in discovering.
"""

from .costs import CostModel
from .engine import run_backtest
from .hypothesis_log import log_run, total_hypotheses_tested
from .metrics import compute_metrics
from .strategies import STRATEGY_REGISTRY, load_daily_data


def _buy_and_hold_baseline(df, hold_days: int, direction: str = "long") -> dict:
    """What holding long unconditionally, re-entering every `hold_days`,
    would have returned over the same period. Necessary context: on an
    index with strong secular drift, almost any long strategy looks
    "good" and almost any short strategy looks "bad" for that reason
    alone, not because of the specific entry logic. Comparing a
    strategy's expectancy to this number is closer to isolating real
    skill than looking at the raw expectancy in isolation."""
    import pandas as pd

    n = len(df)
    always_on = pd.Series(True, index=df.index)
    trades = run_backtest(df, always_on, pd.Series(["N/A"] * n, index=df.index),
                           direction=direction, hold_days=hold_days, cost_model=CostModel())
    m = compute_metrics(trades)
    return {
        "num_trades": m["num_trades"],
        "expectancy_pct": m.get("expectancy_pct"),
        "profit_factor": m.get("profit_factor"),
    }


def run_all_strategies(symbol: str = "^NSEI", days: int = 7000, hold_days: int = 10) -> dict:
    """One pass of every strategy in the registry, same data, same costs,
    same holding period — a fair side-by-side comparison, not a search for
    whichever one looks best."""
    df, regime_series = load_daily_data(symbol, days)
    cost_model = CostModel()
    baseline = _buy_and_hold_baseline(df, hold_days)
    short_baseline = _buy_and_hold_baseline(df, hold_days, direction="short")

    results = {}
    for name, spec in STRATEGY_REGISTRY.items():
        entries = spec["fn"](df, regime_series, **spec["params"])
        trades = run_backtest(
            df, entries, regime_series,
            direction=spec.get("direction", "long"),
            hold_days=hold_days, cost_model=cost_model,
        )
        metrics = compute_metrics(trades)
        log_run(name, {**spec["params"], "hold_days": hold_days}, symbol, days, metrics)
        metrics["direction"] = spec.get("direction", "long")
        metrics["label"] = spec.get("label", name)
        results[name] = metrics

    # Each strategy is compared with being in the market unconditionally in
    # ITS OWN direction — a short strategy against always-short, not against
    # always-long (which charged shorts for the drift twice).
    for r in results.values():
        base = (baseline if r["direction"] == "long" else short_baseline).get("expectancy_pct")
        r["vs_baseline_pct"] = (
            round(r["expectancy_pct"] - base, 3)
            if r.get("expectancy_pct") is not None and base is not None
            else None
        )

    return {
        "symbol": symbol,
        "period": {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "bars": len(df)},
        "hold_days": hold_days,
        "buy_and_hold_baseline": baseline,
        "always_short_baseline": short_baseline,
        "baseline_note": (
            "vs_baseline_pct compares each strategy with being in the market unconditionally in its own "
            "direction, re-entered every hold period, same costs: long strategies against always-long, "
            "short strategies against always-short. NIFTY's upward drift flatters every long strategy and "
            "penalises every short one; this comparison removes that."
        ),
        "results": results,
        "total_hypotheses_tested_all_time": total_hypotheses_tested(),
    }
