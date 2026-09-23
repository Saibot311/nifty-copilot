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
from market_data.nse_indices import top_up as nse_top_up
from quant.indicators import bollinger_bands, ema, rsi
from quant.pipeline import candles_to_df
from quant.regime import classify_regime_series



def ema_pullback_signals(df: pd.DataFrame, regime_series: pd.Series, ema_span: int = 20) -> pd.Series:
    close = df["close"]
    ema_line = ema(close, ema_span)
    above_now = close > ema_line
    above_prev = above_now.shift(1, fill_value=False)
    # fill_value keeps this boolean. .shift(1).fillna(False) produced object dtype in
    # pandas 3, and ~ on objects is integer bit-flip (~True == -2, still truthy), which
    # silently turned "just reclaimed" into "is above" — firing every day of the trend.
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


def ema_rejection_short_signals(
    df: pd.DataFrame, regime_series: pd.Series, ema_span: int = 20
) -> pd.Series:
    """The exact mirror of EMA Pullback, for downtrends: the market is in
    TREND_BEAR, price was above EMA20 yesterday, and has closed back below
    it today — a bounce into the moving average that failed.

    Expressed as a PUT, not a short index position. Every other strategy
    here is long-only, which left the system mute on bearish days; this
    gives it something to say when the trend is down."""
    close = df["close"]
    ema_line = ema(close, ema_span)
    below_now = close < ema_line
    below_prev = below_now.shift(1, fill_value=False)
    just_lost = below_now & ~below_prev
    return just_lost & (regime_series == "TREND_BEAR")


STRATEGY_REGISTRY = {
    "ema_pullback": {
        "fn": ema_pullback_signals, "params": {"ema_span": 20},
        "direction": "long", "option_type": "CE", "label": "EMA Pullback (long)",
    },
    "ema_rejection_short": {
        "fn": ema_rejection_short_signals, "params": {"ema_span": 20},
        "direction": "short", "option_type": "PE", "label": "EMA Rejection (short)",
    },
    "rsi_reversal": {
        "fn": rsi_reversal_signals, "params": {"rsi_period": 14, "oversold": 30},
        "direction": "long", "option_type": "CE", "label": "RSI Oversold Reversal",
    },
    "prev_day_breakout": {
        "fn": prev_day_breakout_signals, "params": {},
        "direction": "long", "option_type": "CE", "label": "Prev-Day-High Breakout",
    },
    "bollinger_reversion": {
        "fn": bollinger_reversion_signals, "params": {"window": 20, "num_std": 2},
        "direction": "long", "option_type": "CE", "label": "Bollinger Band Reversion",
    },
}


from .strategies_v2 import STRATEGY_REGISTRY_V2

STRATEGY_REGISTRY.update(STRATEGY_REGISTRY_V2)

# PCR strategies are added lazily (only when the options archive actually
# has data) rather than at import time, since pcr_signals.py queries
# SQLite on every signal call and importing it up front would make a
# fresh checkout fail before any backfill has run.
def _register_pcr_strategies() -> None:
    try:
        from .pcr_signals import PCR_STRATEGY_REGISTRY
        from storage import archive_stats
        if archive_stats().get("option_bars", 0) > 0:
            STRATEGY_REGISTRY.update(PCR_STRATEGY_REGISTRY)
    except Exception:
        pass  # archive not built yet, or unreachable -- skip silently, not fatal


_register_pcr_strategies()


def load_daily_data(symbol: str = "^NSEI", days: int = 7000) -> tuple[pd.DataFrame, pd.Series]:
    provider = YFinanceProvider()
    candles = provider.get_ohlc(symbol, "1d", date.today() - timedelta(days=days), date.today())
    if len(candles) < 100:
        raise ValueError(f"Only got {len(candles)} daily bars for {symbol} — need 100+ to backtest.")
    df = _top_up_from_nse(candles_to_df(candles), symbol)
    regime_series = classify_regime_series(df)
    return df, regime_series


def _top_up_from_nse(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """See market_data.nse_indices.top_up — one implementation for every loader."""
    return nse_top_up(df, symbol)
