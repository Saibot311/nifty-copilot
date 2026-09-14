"""One fully-specified example strategy, used to prove the backtest engine
end to end. This is the "EMA Pullback" strategy named as an example in the
project's own strategy-database spec — not picked because it's expected to
be profitable (Phase 6 doesn't claim that), but because it's simple enough
to verify by hand.

Rule (long only): the market is in TREND_BULL regime, price was at or
below EMA20 on the previous bar, and has just closed back above EMA20 on
the current bar. Every input to this decision comes from bars up to and
including "today" — never from tomorrow.
"""

from datetime import date, timedelta

import pandas as pd

from market_data import YFinanceProvider
from quant.indicators import ema
from quant.pipeline import candles_to_df
from quant.regime import classify_regime_series

from .costs import CostModel
from .engine import run_backtest
from .hypothesis_log import log_run
from .metrics import compute_metrics


def ema_pullback_signals(df: pd.DataFrame, regime_series: pd.Series, ema_span: int = 20) -> pd.Series:
    close = df["close"]
    ema_line = ema(close, ema_span)
    above_now = close > ema_line
    above_prev = above_now.shift(1).fillna(False)
    just_reclaimed = above_now & ~above_prev
    return just_reclaimed & (regime_series == "TREND_BULL")


def run_ema_pullback_backtest(
    symbol: str = "^NSEI",
    days: int = 2000,
    hold_days: int = 10,
    ema_span: int = 20,
    cost_model: CostModel | None = None,
) -> dict:
    provider = YFinanceProvider()
    candles = provider.get_ohlc(symbol, "1d", date.today() - timedelta(days=days), date.today())
    if len(candles) < 100:
        raise ValueError(f"Only got {len(candles)} daily bars for {symbol} — need 100+ to backtest.")
    df = candles_to_df(candles)

    regime_series = classify_regime_series(df)
    entries = ema_pullback_signals(df, regime_series, ema_span)

    trades = run_backtest(
        df, entries, regime_series,
        direction="long", hold_days=hold_days,
        cost_model=cost_model,
    )
    metrics = compute_metrics(trades)

    params = {"ema_span": ema_span, "hold_days": hold_days}
    log_run("ema_pullback", params, symbol, days, metrics)

    return {
        "strategy": "ema_pullback",
        "params": params,
        "symbol": symbol,
        "period": {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "bars": len(df)},
        "metrics": metrics,
        "trades": [t.__dict__ for t in trades],
    }
