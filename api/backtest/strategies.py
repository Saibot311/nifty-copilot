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
from quant.indicators import bollinger_bands, ema, rsi
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


def rsi_reversal_signals(
    df: pd.DataFrame, regime_series: pd.Series, rsi_period: int = 14, oversold: float = 30
) -> pd.Series:
    """Long when RSI was below the oversold line yesterday and has reclaimed
    it today — a bounce attempt. No regime filter: tested as-is, on purpose,
    to see whether restricting to a regime would even help (a question for
    later, not assumed up front)."""
    r = rsi(df["close"], rsi_period)
    was_oversold = (r.shift(1) < oversold).fillna(False)
    reclaimed = (r >= oversold).fillna(False)
    return was_oversold & reclaimed


def prev_day_breakout_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    """Long when today's close breaks above yesterday's daily high — the
    purest possible price-action signal, no indicator involved at all."""
    prev_high = df["high"].shift(1)
    return (df["close"] > prev_high).fillna(False)


def bollinger_reversion_signals(
    df: pd.DataFrame, regime_series: pd.Series, window: int = 20, num_std: float = 2
) -> pd.Series:
    """Long when price closed below the lower Bollinger Band yesterday and
    has reclaimed it today — a mean-reversion bet, the opposite philosophy
    from the trend-following EMA Pullback strategy."""
    bands = bollinger_bands(df["close"], window, num_std)
    was_below = (df["close"].shift(1) < bands["lower"].shift(1)).fillna(False)
    reclaimed = (df["close"] >= bands["lower"]).fillna(False)
    return was_below & reclaimed


STRATEGY_REGISTRY = {
    "ema_pullback": {"fn": ema_pullback_signals, "params": {"ema_span": 20}},
    "rsi_reversal": {"fn": rsi_reversal_signals, "params": {"rsi_period": 14, "oversold": 30}},
    "prev_day_breakout": {"fn": prev_day_breakout_signals, "params": {}},
    "bollinger_reversion": {"fn": bollinger_reversion_signals, "params": {"window": 20, "num_std": 2}},
}


def load_daily_data(symbol: str = "^NSEI", days: int = 7000) -> tuple[pd.DataFrame, pd.Series]:
    provider = YFinanceProvider()
    candles = provider.get_ohlc(symbol, "1d", date.today() - timedelta(days=days), date.today())
    if len(candles) < 100:
        raise ValueError(f"Only got {len(candles)} daily bars for {symbol} — need 100+ to backtest.")
    df = candles_to_df(candles)
    regime_series = classify_regime_series(df)
    return df, regime_series


def run_ema_pullback_backtest(
    symbol: str = "^NSEI",
    days: int = 2000,
    hold_days: int = 10,
    ema_span: int = 20,
    cost_model: CostModel | None = None,
) -> dict:
    df, regime_series = load_daily_data(symbol, days)
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
