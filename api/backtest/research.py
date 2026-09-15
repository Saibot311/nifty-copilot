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
from .strategies import STRATEGY_REGISTRY, ema_pullback_signals, load_daily_data


def run_all_strategies(symbol: str = "^NSEI", days: int = 7000, hold_days: int = 10) -> dict:
    """One pass of every strategy in the registry, same data, same costs,
    same holding period — a fair side-by-side comparison, not a search for
    whichever one looks best."""
    df, regime_series = load_daily_data(symbol, days)
    cost_model = CostModel()

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

    return {
        "symbol": symbol,
        "period": {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "bars": len(df)},
        "hold_days": hold_days,
        "results": results,
        "total_hypotheses_tested_all_time": total_hypotheses_tested(),
    }


def run_ema_pullback_param_sweep(
    symbol: str = "^NSEI",
    days: int = 7000,
    ema_spans: list[int] = [10, 15, 20, 25, 30],
    hold_days_options: list[int] = [5, 10, 15, 20],
) -> dict:
    """Parameter-robustness check: if EMA Pullback only 'works' at exactly
    ema_span=20/hold_days=10 and falls apart one step either side, that's a
    sign of overfitting to noise rather than a real, robust effect."""
    df, regime_series = load_daily_data(symbol, days)
    cost_model = CostModel()

    grid = []
    for ema_span in ema_spans:
        for hold_days in hold_days_options:
            entries = ema_pullback_signals(df, regime_series, ema_span=ema_span)
            trades = run_backtest(
                df, entries, regime_series, direction="long", hold_days=hold_days, cost_model=cost_model
            )
            metrics = compute_metrics(trades)
            log_run("ema_pullback", {"ema_span": ema_span, "hold_days": hold_days}, symbol, days, metrics)
            grid.append({
                "ema_span": ema_span,
                "hold_days": hold_days,
                "num_trades": metrics["num_trades"],
                "expectancy_pct": metrics.get("expectancy_pct"),
                "profit_factor": metrics.get("profit_factor"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            })

    positive = sum(1 for cell in grid if (cell.get("expectancy_pct") or 0) > 0)
    return {
        "symbol": symbol,
        "period": {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "bars": len(df)},
        "grid": grid,
        "combinations_tested": len(grid),
        "combinations_with_positive_expectancy": positive,
        "total_hypotheses_tested_all_time": total_hypotheses_tested(),
    }
