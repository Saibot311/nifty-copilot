"""Phase 8: does a strategy survive outside the data it was picked on?

Generalized to any strategy in STRATEGY_REGISTRY (originally hardcoded to
EMA Pullback only) so the same rigor can be applied to any candidate, not
just the first one built.

Two checks:
1. Walk-forward folds — split the full history into chronological chunks
   and look at performance fold by fold, to see if the edge is concentrated
   in one lucky period or holds up broadly over time.
2. Development/holdout split — a stricter, single train/test cut. The
   strategy only earns APPROVED if, in both halves, it is profitable and
   beats being in the market unconditionally in the same direction, with
   a real sample size in the holdout.

Important honesty note, not a footnote: every strategy in the registry has
hand-fixed parameters, not fit to data — there's no optimization step
whose result could leak from a holdout back into the rule the way it
would for a machine-learned model. So this *is* a genuine test of whether
each rule's edge is stable over time. What it is NOT: a clean test of the
*selection* process — Phase 7 already looked at the full history
(holdout included) when ranking strategies against each other. A fully
rigorous version would re-run strategy discovery using only the
development period and confirm the same strategy gets picked before ever
looking at the holdout. That's a real limitation of this pass, kept
visible rather than glossed over.
"""

import math
import statistics
from datetime import timedelta

from .costs import CostModel
from .engine import run_backtest
from .hypothesis_log import log_run
from .metrics import compute_metrics
from .research import _buy_and_hold_baseline
from .strategies import STRATEGY_REGISTRY, load_daily_data


def _methodology_note(label: str) -> str:
    return (
        f"{label}'s parameters were fixed by hand, not fit to data, so there's no optimization "
        "step whose result could leak from the holdout back into the rule — this is a genuine test "
        "of the rule's stability over time. The real limitation: Phase 7 already looked at the FULL "
        "history (holdout included) when ranking this strategy against the others in the registry, "
        "so this is not a perfectly clean test of that selection process. A fully rigorous version "
        "would re-run strategy discovery using only the development period and confirm the same "
        "strategy would have been chosen before ever looking at the holdout."
    )


def _spec(strategy_name: str) -> dict:
    if strategy_name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{strategy_name}'. Choose one of {list(STRATEGY_REGISTRY)}.")
    return STRATEGY_REGISTRY[strategy_name]


def _run_full_trades(strategy_name: str, symbol: str, days: int, hold_days: int):
    spec = _spec(strategy_name)
    df, regime_series = load_daily_data(symbol, days)
    entries = spec["fn"](df, regime_series, **spec["params"])
    trades = run_backtest(
        df, entries, regime_series,
        direction=spec.get("direction", "long"), hold_days=hold_days, cost_model=CostModel(),
    )
    return df, trades


def run_walk_forward(
    strategy_name: str = "ema_pullback", symbol: str = "^NSEI", days: int = 7000,
    hold_days: int = 10, n_folds: int = 5,
) -> dict:
    spec = _spec(strategy_name)
    label = spec.get("label", strategy_name)
    df, trades = _run_full_trades(strategy_name, symbol, days, hold_days)

    start_date = df.index[0].date()
    end_date = df.index[-1].date()
    total_days = (end_date - start_date).days
    fold_len = total_days / n_folds

    fold_bounds = []
    for i in range(n_folds):
        f_start = start_date + timedelta(days=int(i * fold_len))
        f_end = end_date if i == n_folds - 1 else start_date + timedelta(days=int((i + 1) * fold_len))
        fold_bounds.append((str(f_start), str(f_end)))

    folds = []
    for f_start, f_end in fold_bounds:
        fold_trades = [t for t in trades if f_start <= t.entry_date <= f_end]
        folds.append({"period": {"start": f_start, "end": f_end}, "metrics": compute_metrics(fold_trades)})

    folds_with_trades = [f for f in folds if f["metrics"]["num_trades"] > 0]
    positive_folds = sum(1 for f in folds_with_trades if (f["metrics"].get("expectancy_pct") or 0) > 0)

    overall_metrics = compute_metrics(trades)
    log_run(
        f"{strategy_name}_walkforward", {"hold_days": hold_days, "n_folds": n_folds},
        symbol, days, overall_metrics,
    )

    return {
        "strategy": strategy_name,
        "label": label,
        "symbol": symbol,
        "period": {"start": str(start_date), "end": str(end_date)},
        "n_folds": n_folds,
        "folds": folds,
        "folds_with_positive_expectancy": positive_folds,
        "folds_with_any_trades": len(folds_with_trades),
        "methodology_note": _methodology_note(label),
    }


def run_holdout_test(
    strategy_name: str = "ema_pullback", symbol: str = "^NSEI", days: int = 7000,
    hold_days: int = 10, train_frac: float = 0.7, min_holdout_trades: int = 15,
) -> dict:
    spec = _spec(strategy_name)
    label = spec.get("label", strategy_name)
    df, trades = _run_full_trades(strategy_name, symbol, days, hold_days)

    start_date = df.index[0].date()
    end_date = df.index[-1].date()
    total_days = (end_date - start_date).days
    split_date = str(start_date + timedelta(days=int(total_days * train_frac)))

    dev_trades = [t for t in trades if t.entry_date < split_date]
    holdout_trades = [t for t in trades if t.entry_date >= split_date]

    dev_metrics = compute_metrics(dev_trades)
    holdout_metrics = compute_metrics(holdout_trades)

    dev_expectancy = dev_metrics.get("expectancy_pct") or 0
    holdout_expectancy = holdout_metrics.get("expectancy_pct") or 0
    holdout_n = holdout_metrics.get("num_trades") or 0

    direction = spec.get("direction", "long")
    dev_baseline = _buy_and_hold_baseline(df[df.index < split_date], hold_days, direction).get("expectancy_pct") or 0
    holdout_baseline = _buy_and_hold_baseline(df[df.index >= split_date], hold_days, direction).get("expectancy_pct") or 0

    holdout_t = excess_t_stat([t.net_return_pct for t in holdout_trades], holdout_baseline)
    status, reason = holdout_verdict(
        dev_expectancy, holdout_expectancy, dev_baseline, holdout_baseline,
        holdout_n, min_holdout_trades, direction, holdout_t,
    )

    log_run(
        f"{strategy_name}_holdout", {"hold_days": hold_days, "train_frac": train_frac},
        symbol, days, holdout_metrics,
    )

    return {
        "strategy": strategy_name,
        "label": label,
        "symbol": symbol,
        "split_date": split_date,
        "development": {"period": {"start": str(start_date), "end": split_date}, "metrics": dev_metrics},
        "holdout": {"period": {"start": split_date, "end": str(end_date)}, "metrics": holdout_metrics},
        "baseline": {"direction": direction, "development_expectancy_pct": dev_baseline, "holdout_expectancy_pct": holdout_baseline},
        "holdout_excess_t_stat": holdout_t,
        "status": status,
        "reason": reason,
        "methodology_note": _methodology_note(label),
    }


MIN_T_STAT = 2.0


def excess_t_stat(returns: list[float], baseline: float) -> float | None:
    """t-statistic of mean per-trade return over the baseline. ~2 is the
    conventional line where an edge stops looking like luck."""
    if len(returns) < 2:
        return None
    sd = statistics.stdev(returns)
    if sd == 0:
        return None
    return round((statistics.mean(returns) - baseline) / (sd / math.sqrt(len(returns))), 2)


def holdout_verdict(
    dev_exp: float, holdout_exp: float, dev_baseline: float, holdout_baseline: float,
    holdout_n: int, min_holdout_trades: int, direction: str = "long",
    holdout_t: float | None = None, min_t: float = MIN_T_STAT, baseline_label: str | None = None,
    unit: str = "%",
) -> tuple[str, str]:
    """A strategy must make money AND beat simply being in the market in the
    same direction, in both periods. "Positive" alone isn't enough: NIFTY's
    drift made two long strategies APPROVED at +0.04% and +0.06% per trade
    while always-long earned more over the same holdout."""
    side = baseline_label or ("always-long" if direction == "long" else "always-short")

    def f(v: float) -> str:
        return f"₹{round(v):,}" if unit == "₹" else f"{v}%"

    if dev_exp <= 0 or holdout_exp <= 0:
        return "REJECTED", "Lost money in the development period, the holdout period, or both."
    if dev_exp <= dev_baseline or holdout_exp <= holdout_baseline:
        return "REJECTED", (
            f"Profitable, but no better than {side}: development {f(dev_exp)} vs "
            f"{f(dev_baseline)}, holdout {f(holdout_exp)} vs {f(holdout_baseline)} per trade. "
            "The return comes from the market, not the pattern."
        )
    if holdout_n < min_holdout_trades:
        return "CONDITIONAL", (
            f"Beats {side} in both periods, but only {holdout_n} holdout trades — "
            f"below the {min_holdout_trades}-trade bar for confidence."
        )
    if holdout_t is None or holdout_t < min_t:
        return "REJECTED", (
            f"Beats {side}, but by too little to tell from luck: holdout edge "
            f"{f(round(holdout_exp - holdout_baseline, 3))} per trade over {holdout_n} trades, t = {holdout_t} "
            f"(needs t >= {min_t})."
        )
    return "APPROVED", (
        f"Beats {side} in both development ({f(dev_exp)} vs {f(dev_baseline)}) and holdout "
        f"({f(holdout_exp)} vs {f(holdout_baseline)}), with {holdout_n} holdout trades and t = {holdout_t}."
    )


def evaluate_strategy(
    strategy_name: str = "ema_pullback", symbol: str = "^NSEI", days: int = 7000, hold_days: int = 10,
    n_folds: int = 5, train_frac: float = 0.7, min_holdout_trades: int = 15,
    min_fold_win_share: float = 0.6,
) -> dict:
    """Combines both checks into one honest final verdict — deliberately
    stricter than looking at either alone. A strategy that passes the
    holdout split but is only positive in a minority of chronological
    folds is NOT "robust over time," even though the single train/test cut
    looks fine; this function is what stops that from being overstated as
    APPROVED.
    """
    spec = _spec(strategy_name)
    label = spec.get("label", strategy_name)
    wf = run_walk_forward(strategy_name, symbol, days, hold_days, n_folds)
    ho = run_holdout_test(strategy_name, symbol, days, hold_days, train_frac, min_holdout_trades)

    fold_win_share = (
        wf["folds_with_positive_expectancy"] / wf["folds_with_any_trades"]
        if wf["folds_with_any_trades"] > 0 else 0
    )
    holdout_passes = ho["status"] == "APPROVED"
    folds_pass = fold_win_share >= min_fold_win_share

    if not holdout_passes:
        final_status = ho["status"]  # REJECTED or CONDITIONAL, already explained
        final_reason = ho["reason"]
    elif not folds_pass:
        final_status = "CONDITIONAL"
        final_reason = (
            f"Holdout split alone looks fine, but only {wf['folds_with_positive_expectancy']} of "
            f"{wf['folds_with_any_trades']} chronological folds ({fold_win_share:.0%}) had positive "
            f"expectancy — below the {min_fold_win_share:.0%} bar for calling this robust over time. "
            "A single train/test split can look good by masking inconsistency the fold breakdown reveals."
        )
    else:
        final_status = "APPROVED"
        final_reason = (
            f"Passes both checks: positive in development and holdout, and "
            f"{wf['folds_with_positive_expectancy']}/{wf['folds_with_any_trades']} folds positive."
        )

    return {
        "strategy": strategy_name,
        "label": label,
        "final_status": final_status,
        "final_reason": final_reason,
        "walk_forward": wf,
        "holdout": ho,
        "methodology_note": _methodology_note(label),
    }
