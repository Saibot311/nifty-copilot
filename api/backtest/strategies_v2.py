"""A broader, symmetric strategy set — every category a real options desk
actually watches, with a call-side and put-side version of each wherever
the setup has a natural mirror. Grounded in what came up repeatedly
researching real practice (2026-09-15): 9/21 EMA and Supertrend flips,
MACD crossovers, RSI/Bollinger mean-reversion, breakout patterns,
candlestick reversals, and PCR as a contrarian sentiment gauge.

Every signal here is exploratory until it's been through Phase 7/8 the
same as EMA Pullback was — adding a strategy to the registry does not
make it validated, and most of these will very likely turn out to have no
edge, the same way 3 of the original 4 did. That's expected, not a
problem to fix by tuning until something looks good.
"""

import pandas as pd

from quant.indicators import bollinger_bands, ema, macd, rsi, stochastic, supertrend

# ---------------------------------------------------------------------------
# Trend-following: a direction change/crossover IS the entry signal.
# ---------------------------------------------------------------------------

def supertrend_flip_bull_signals(df: pd.DataFrame, regime_series: pd.Series, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    st = supertrend(df, period, multiplier)
    flipped_up = (st["direction"] == 1) & (st["direction"].shift(1) == -1)
    return flipped_up.fillna(False)


def supertrend_flip_bear_signals(df: pd.DataFrame, regime_series: pd.Series, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    st = supertrend(df, period, multiplier)
    flipped_down = (st["direction"] == -1) & (st["direction"].shift(1) == 1)
    return flipped_down.fillna(False)


def ema_crossover_bull_signals(df: pd.DataFrame, regime_series: pd.Series, fast: int = 9, slow: int = 21) -> pd.Series:
    """The 9/21 EMA cross — the most commonly cited intraday setup in
    practice, applied here on daily bars."""
    f, s = ema(df["close"], fast), ema(df["close"], slow)
    cross_up = (f > s) & (f.shift(1) <= s.shift(1))
    return cross_up.fillna(False)


def ema_crossover_bear_signals(df: pd.DataFrame, regime_series: pd.Series, fast: int = 9, slow: int = 21) -> pd.Series:
    f, s = ema(df["close"], fast), ema(df["close"], slow)
    cross_down = (f < s) & (f.shift(1) >= s.shift(1))
    return cross_down.fillna(False)


def macd_bull_cross_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    m = macd(df["close"])
    cross_up = (m["macd"] > m["signal"]) & (m["macd"].shift(1) <= m["signal"].shift(1))
    return cross_up.fillna(False)


def macd_bear_cross_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    m = macd(df["close"])
    cross_down = (m["macd"] < m["signal"]) & (m["macd"].shift(1) >= m["signal"].shift(1))
    return cross_down.fillna(False)


# ---------------------------------------------------------------------------
# Mean-reversion: extreme reading, then a reclaim in the other direction.
# ---------------------------------------------------------------------------

def rsi_overbought_reversal_signals(df: pd.DataFrame, regime_series: pd.Series, rsi_period: int = 14, overbought: float = 70) -> pd.Series:
    """Mirror of the existing RSI Oversold Reversal, for the top side."""
    r = rsi(df["close"], rsi_period)
    was_overbought = (r.shift(1) > overbought).fillna(False)
    lost_it = (r <= overbought).fillna(False)
    return was_overbought & lost_it


def bollinger_upper_rejection_signals(df: pd.DataFrame, regime_series: pd.Series, window: int = 20, num_std: float = 2) -> pd.Series:
    """Mirror of the existing Bollinger lower-band reversion, for the top
    band — price tags the upper band then closes back inside it."""
    bands = bollinger_bands(df["close"], window, num_std)
    was_above = (df["close"].shift(1) > bands["upper"].shift(1)).fillna(False)
    rejected = (df["close"] <= bands["upper"]).fillna(False)
    return was_above & rejected


def stochastic_oversold_reversal_signals(df: pd.DataFrame, regime_series: pd.Series, oversold: float = 20) -> pd.Series:
    sto = stochastic(df)
    was_below = (sto["k"].shift(1) < oversold).fillna(False)
    reclaimed = (sto["k"] >= oversold).fillna(False)
    return was_below & reclaimed


def stochastic_overbought_reversal_signals(df: pd.DataFrame, regime_series: pd.Series, overbought: float = 80) -> pd.Series:
    sto = stochastic(df)
    was_above = (sto["k"].shift(1) > overbought).fillna(False)
    lost_it = (sto["k"] <= overbought).fillna(False)
    return was_above & lost_it


# ---------------------------------------------------------------------------
# Breakouts: price clears a level it hasn't cleared recently.
# ---------------------------------------------------------------------------

def prev_day_breakdown_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    """Mirror of the existing prev-day-high breakout: today's close breaks
    below yesterday's low."""
    prev_low = df["low"].shift(1)
    return (df["close"] < prev_low).fillna(False)


def year_high_breakout_signals(df: pd.DataFrame, regime_series: pd.Series, lookback: int = 252) -> pd.Series:
    """Close breaks above the highest close of the prior `lookback` bars
    (shifted so today's own bar can't count toward its own breakout)."""
    rolling_high = df["close"].shift(1).rolling(lookback).max()
    return (df["close"] > rolling_high).fillna(False)


def year_low_breakdown_signals(df: pd.DataFrame, regime_series: pd.Series, lookback: int = 252) -> pd.Series:
    rolling_low = df["close"].shift(1).rolling(lookback).min()
    return (df["close"] < rolling_low).fillna(False)


def squeeze_breakout_up_signals(df: pd.DataFrame, regime_series: pd.Series, window: int = 20, squeeze_lookback: int = 60, squeeze_pct: float = 0.2) -> pd.Series:
    """Bollinger-width compresses into its lowest `squeeze_pct` percentile
    over `squeeze_lookback` bars — a volatility-contraction setup — then
    price breaks the upper band."""
    bands = bollinger_bands(df["close"], window)
    width = (bands["upper"] - bands["lower"]) / bands["mid"]
    was_squeezed = (width.shift(1) <= width.shift(1).rolling(squeeze_lookback).quantile(squeeze_pct)).fillna(False)
    broke_up = (df["close"] > bands["upper"]).fillna(False)
    return was_squeezed & broke_up


def squeeze_breakout_down_signals(df: pd.DataFrame, regime_series: pd.Series, window: int = 20, squeeze_lookback: int = 60, squeeze_pct: float = 0.2) -> pd.Series:
    bands = bollinger_bands(df["close"], window)
    width = (bands["upper"] - bands["lower"]) / bands["mid"]
    was_squeezed = (width.shift(1) <= width.shift(1).rolling(squeeze_lookback).quantile(squeeze_pct)).fillna(False)
    broke_down = (df["close"] < bands["lower"]).fillna(False)
    return was_squeezed & broke_down


# ---------------------------------------------------------------------------
# Candlestick reversals: filtered to an actual local swing, per the
# research finding that these need to appear at a swing high/low to have
# any documented edge — used bare, they're closer to noise.
# ---------------------------------------------------------------------------

# Trailing windows only. These were originally rolling(center=True), which
# at bar i looks at bars i+1 and i+2 — a candle was only called "at a swing
# low" once the backtest already knew price didn't go lower over the next
# two days. That's look-ahead (I1). Now: the bar's low is the lowest of the
# last `window` bars, which a trader can actually know at that close.
def _is_swing_low(df: pd.DataFrame, window: int = 5) -> pd.Series:
    return df["low"] == df["low"].rolling(window).min()


def _is_swing_high(df: pd.DataFrame, window: int = 5) -> pd.Series:
    return df["high"] == df["high"].rolling(window).max()


def bullish_engulfing_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    prev_red = df["close"].shift(1) < df["open"].shift(1)
    curr_green = df["close"] > df["open"]
    engulfs = (df["open"] <= df["close"].shift(1)) & (df["close"] >= df["open"].shift(1))
    at_swing = _is_swing_low(df).shift(1, fill_value=False)  # swing formed on the prior bar
    return (prev_red & curr_green & engulfs & at_swing).fillna(False)


def bearish_engulfing_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    prev_green = df["close"].shift(1) > df["open"].shift(1)
    curr_red = df["close"] < df["open"]
    engulfs = (df["open"] >= df["close"].shift(1)) & (df["close"] <= df["open"].shift(1))
    at_swing = _is_swing_high(df).shift(1, fill_value=False)
    return (prev_green & curr_red & engulfs & at_swing).fillna(False)


def hammer_reversal_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    body = (df["close"] - df["open"]).abs()
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    is_hammer = (lower_wick >= 2 * body) & (upper_wick <= body * 0.5) & (body > 0)
    at_swing = _is_swing_low(df)
    return (is_hammer & at_swing).fillna(False)


def shooting_star_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    body = (df["close"] - df["open"]).abs()
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    is_star = (upper_wick >= 2 * body) & (lower_wick <= body * 0.5) & (body > 0)
    at_swing = _is_swing_high(df)
    return (is_star & at_swing).fillna(False)


STRATEGY_REGISTRY_V2 = {
    "supertrend_flip_bull": {"fn": supertrend_flip_bull_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "Supertrend Flip (bull)"},
    "supertrend_flip_bear": {"fn": supertrend_flip_bear_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Supertrend Flip (bear)"},
    "ema_crossover_bull": {"fn": ema_crossover_bull_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "9/21 EMA Crossover (bull)"},
    "ema_crossover_bear": {"fn": ema_crossover_bear_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "9/21 EMA Crossover (bear)"},
    "macd_bull_cross": {"fn": macd_bull_cross_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "MACD Bullish Crossover"},
    "macd_bear_cross": {"fn": macd_bear_cross_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "MACD Bearish Crossover"},
    "rsi_overbought_reversal": {"fn": rsi_overbought_reversal_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "RSI Overbought Reversal"},
    "bollinger_upper_rejection": {"fn": bollinger_upper_rejection_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Bollinger Upper Rejection"},
    "stochastic_oversold_reversal": {"fn": stochastic_oversold_reversal_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "Stochastic Oversold Reversal"},
    "stochastic_overbought_reversal": {"fn": stochastic_overbought_reversal_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Stochastic Overbought Reversal"},
    "prev_day_breakdown": {"fn": prev_day_breakdown_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Prev-Day-Low Breakdown"},
    "year_high_breakout": {"fn": year_high_breakout_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "52-Week High Breakout"},
    "year_low_breakdown": {"fn": year_low_breakdown_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "52-Week Low Breakdown"},
    "squeeze_breakout_up": {"fn": squeeze_breakout_up_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "Volatility Squeeze Breakout (up)"},
    "squeeze_breakout_down": {"fn": squeeze_breakout_down_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Volatility Squeeze Breakout (down)"},
    "bullish_engulfing": {"fn": bullish_engulfing_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "Bullish Engulfing (at swing low)"},
    "bearish_engulfing": {"fn": bearish_engulfing_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Bearish Engulfing (at swing high)"},
    "hammer_reversal": {"fn": hammer_reversal_signals, "params": {}, "direction": "long", "option_type": "CE", "label": "Hammer (at swing low)"},
    "shooting_star": {"fn": shooting_star_signals, "params": {}, "direction": "short", "option_type": "PE", "label": "Shooting Star (at swing high)"},
}
