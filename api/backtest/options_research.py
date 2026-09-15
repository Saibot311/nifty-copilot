"""Answers the real question for options: given that a signal fired, WHICH
contract should you have bought?

Sweeps strike offset (ITM / ATM / OTM) against expiry distance and reports
what each combination actually returned on premium. That turns strike
selection from a rule of thumb into a measured result.

Multiple-comparisons warning is not optional here: sweeping a grid of
strike × expiry combinations against one signal is precisely the kind of
search that produces good-looking numbers by chance. Every combination is
logged, the count is reported alongside the results, and the best cell is
never presented as "the answer" without that context.
"""

import pandas as pd

from .engine import Trade
from .hypothesis_log import log_run, total_hypotheses_tested
from .metrics import compute_metrics
from .options_engine import OptionsCostModel, run_options_backtest
from .strategies import ema_pullback_signals, load_daily_data


def _as_index_trades(option_trades) -> list[Trade]:
    """Adapts option trades into the shape compute_metrics expects, so the
    metric definitions stay in one place rather than being reimplemented."""
    return [
        Trade(
            entry_date=t.entry_date,
            exit_date=t.exit_date,
            direction="long",
            entry_price=t.entry_premium,
            exit_price=t.exit_premium,
            regime_at_entry="TREND_BULL",
            holding_days=t.holding_days,
            gross_return_pct=t.gross_return_pct,
            cost_pct=t.cost_pct,
            net_return_pct=t.net_return_pct,
        )
        for t in option_trades
    ]


def _signal_context(symbol: str, days: int, ema_span: int):
    df, regime_series = load_daily_data(symbol, days)
    entries = ema_pullback_signals(df, regime_series, ema_span=ema_span)
    trading_days = [str(d.date()) for d in df.index]
    signal_dates = [str(df.index[i].date()) for i in range(len(df)) if bool(entries.iloc[i])]
    spot_series = pd.Series(df["close"].values, index=trading_days)
    return signal_dates, spot_series, trading_days


def run_options_strike_sweep(
    symbol: str = "^NSEI",
    days: int = 3000,
    ema_span: int = 20,
    hold_days: int = 10,
    strike_offsets: list[float] | None = None,
    expiry_windows: list[int] | None = None,
    min_open_interest: float = 1000,
) -> dict:
    strike_offsets = strike_offsets if strike_offsets is not None else [-300, -150, 0, 150, 300, 500]
    expiry_windows = expiry_windows if expiry_windows is not None else [20, 30, 45]

    signal_dates, spot_series, trading_days = _signal_context(symbol, days, ema_span)
    cost_model = OptionsCostModel()

    grid = []
    for offset in strike_offsets:
        for min_dte in expiry_windows:
            option_trades = run_options_backtest(
                signal_dates=signal_dates,
                spot_series=spot_series,
                trading_days=trading_days,
                option_type="CE",
                strike_offset_pts=offset,
                min_days_to_expiry=min_dte,
                hold_days=hold_days,
                min_open_interest=min_open_interest,
                cost_model=cost_model,
            )
            metrics = compute_metrics(_as_index_trades(option_trades))
            log_run(
                "ema_pullback_options",
                {"strike_offset": offset, "min_days_to_expiry": min_dte, "hold_days": hold_days},
                symbol, days, metrics,
            )
            grid.append({
                "strike_offset_pts": offset,
                "moneyness": "ITM" if offset < 0 else ("ATM" if offset == 0 else "OTM"),
                "min_days_to_expiry": min_dte,
                "num_trades": metrics["num_trades"],
                "win_rate": metrics.get("win_rate"),
                "expectancy_pct": metrics.get("expectancy_pct"),
                "profit_factor": metrics.get("profit_factor"),
                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                "avg_win_pct": metrics.get("avg_win_pct"),
                "avg_loss_pct": metrics.get("avg_loss_pct"),
                "sample_size_warning": metrics.get("sample_size_warning"),
            })

    cells_with_trades = [c for c in grid if c["num_trades"] > 0]
    positive = [c for c in cells_with_trades if (c["expectancy_pct"] or 0) > 0]
    best = max(cells_with_trades, key=lambda c: c["expectancy_pct"] or -999, default=None)

    return {
        "strategy": "ema_pullback",
        "symbol": symbol,
        "signal_count": len(signal_dates),
        "hold_days": hold_days,
        "grid": grid,
        "combinations_tested": len(grid),
        "combinations_with_trades": len(cells_with_trades),
        "combinations_with_positive_expectancy": len(positive),
        "best_cell": best,
        "total_hypotheses_tested_all_time": total_hypotheses_tested(),
        "multiple_comparisons_note": (
            f"{len(grid)} strike/expiry combinations were tested against the same signal. "
            "With that many tries, the best-looking cell is partly luck — treat it as a "
            "hypothesis to test on fresh data, not a validated choice. Compare the whole "
            "grid's consistency rather than trusting the single best number."
        ),
        "cost_note": (
            "Returns are on PREMIUM and include modeled costs "
            f"({cost_model.round_trip_cost_fraction() * 100:.2f}% round trip, dominated by an assumed "
            f"{cost_model.premium_slippage_pct * 100:.1f}% bid-ask slippage per side). Real option "
            "spreads vary with strike liquidity and can be worse, especially far OTM."
        ),
    }
