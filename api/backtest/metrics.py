"""All metrics your project plan asked for, computed from real simulated
trades. A strategy with under 30 trades gets an explicit low-sample
warning attached — this is a lightweight first step toward the
multiple-comparisons discipline the project spec calls for; the full
false-discovery-rate correction across many tested strategies is Phase 8's
job, once there's more than one strategy to compare.
"""

import numpy as np

from .engine import Trade


def _subset_metrics(subset: list[Trade]) -> dict:
    if not subset:
        return {"num_trades": 0}
    returns = np.array([t.net_return_pct for t in subset])
    wins = returns[returns > 0]
    return {
        "num_trades": len(subset),
        "win_rate": round(len(wins) / len(subset), 3),
        "avg_return_pct": round(float(returns.mean()), 3),
    }


def compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"num_trades": 0, "note": "No trades generated for this strategy/period — cannot compute metrics."}

    returns = np.array([t.net_return_pct for t in trades])
    wins = returns[returns > 0]
    losses = returns[returns <= 0]

    num_trades = len(trades)
    win_rate = len(wins) / num_trades
    loss_rate = 1 - win_rate
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0  # negative or zero
    expectancy = win_rate * avg_win + loss_rate * avg_loss

    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(abs(losses.sum())) if len(losses) else 0.0
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    equity_curve = np.cumprod(1 + returns / 100)
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown_pct = float(drawdown.min() * 100)

    avg_holding_days = float(np.mean([t.holding_days for t in trades]))

    # Sharpe/Sortino approximated from per-trade returns, annualized via the
    # implied trades/year from average holding period. A true Sharpe wants a
    # daily mark-to-market equity curve — documented approximation, not a
    # more precise number than it actually is.
    trades_per_year = 252 / avg_holding_days if avg_holding_days > 0 else 0
    std = returns.std(ddof=1) if num_trades > 1 else 0.0
    sharpe = (returns.mean() / std * np.sqrt(trades_per_year)) if std > 0 else None

    downside = returns[returns < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else 0.0
    sortino = (returns.mean() / downside_std * np.sqrt(trades_per_year)) if downside_std > 0 else None

    by_year: dict[str, list[Trade]] = {}
    by_regime: dict[str, list[Trade]] = {}
    for t in trades:
        by_year.setdefault(t.entry_date[:4], []).append(t)
        by_regime.setdefault(t.regime_at_entry, []).append(t)

    sample_warning = None
    if num_trades < 30:
        sample_warning = (
            f"Only {num_trades} trades — too small a sample to call this validated. "
            "Treat these numbers as exploratory, not confirmatory."
        )

    return {
        "num_trades": num_trades,
        "win_rate": round(win_rate, 3),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "expectancy_pct": round(expectancy, 3),
        "profit_factor": round(profit_factor, 3) if np.isfinite(profit_factor) else None,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio_approx": round(float(sharpe), 3) if sharpe is not None else None,
        "sortino_ratio_approx": round(float(sortino), 3) if sortino is not None else None,
        "avg_holding_days": round(avg_holding_days, 1),
        "long": _subset_metrics([t for t in trades if t.direction == "long"]),
        "short": _subset_metrics([t for t in trades if t.direction == "short"]),
        "by_year": {y: _subset_metrics(ts) for y, ts in sorted(by_year.items())},
        "by_regime": {r: _subset_metrics(ts) for r, ts in by_regime.items()},
        "time_of_day": "N/A — daily bars only, no intraday timestamps yet",
        "sample_size_warning": sample_warning,
    }
