"""Realistic drawdown for option trades — the one piece kept from the old
EMA Pullback strike sweep (that sweep is superseded by pattern_options.py)."""

from .options_engine import OptionTrade

# Option trades swing far more per-trade than index trades (+244%, -79% in
# one real backtest run) -- full capital reinvestment between trades, which
# compute_metrics assumes for the index engine, mathematically erodes
# equity toward zero over a long enough sequence even with a POSITIVE
# average edge (volatility drag). No real trader stakes the whole account
# on one option position repeatedly. 10% is a conservative, realistic
# fixed-fraction size for a leveraged options position -- position sizing
# is a real, separate decision from the signal itself, not modeled beyond
# this one assumption.
REALISTIC_POSITION_FRACTION = 0.10


def _realistic_max_drawdown_pct(option_trades: list[OptionTrade], position_fraction: float = REALISTIC_POSITION_FRACTION) -> float | None:
    if not option_trades:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in option_trades:
        equity *= 1 + position_fraction * t.net_return_pct / 100
        peak = max(peak, equity)
        max_dd = min(max_dd, (equity - peak) / peak)
    return round(max_dd * 100, 2)
