"""Deterministic indicator calculations. Every formula here is a standard,
published definition — nothing estimated, nothing from an LLM. If a number
can't be computed (not enough history, missing column), the function should
raise or return None — never silently substitute a guess.
"""

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder's smoothing (the original RSI definition), not a plain SMA.
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "histogram": macd_line - signal_line,
    })


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1)
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2) -> pd.DataFrame:
    """Bollinger's definition uses the population standard deviation (divide
    by n), as do TA-Lib and TradingView. pandas' rolling().std() defaults to
    the sample one (divide by n-1), which made every band about 2.6% wider
    than the published indicator and changed 76 signals across the two
    patterns built on it."""
    mid = sma(series, window)
    std = series.rolling(window).std(ddof=0)
    return pd.DataFrame({
        "mid": mid,
        "upper": mid + num_std * std,
        "lower": mid - num_std * std,
    })


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    smoothed_tr = tr.ewm(alpha=1 / period, adjust=False).mean()
    smoothed_plus_dm = pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean()
    smoothed_minus_dm = pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def historical_volatility(series: pd.Series, window: int = 20, trading_days: int = 252) -> pd.Series:
    log_returns = np.log(series / series.shift(1))
    return log_returns.rolling(window).std() * np.sqrt(trading_days) * 100


def relative_volume(df: pd.DataFrame, window: int = 20) -> pd.Series:
    return df["volume"] / df["volume"].rolling(window).mean()


def session_vwap(intraday_df: pd.DataFrame) -> pd.Series:
    """True VWAP: cumulative volume-weighted typical price, reset every
    trading session. `intraday_df` must have a datetime index and
    high/low/close/volume columns at intraday granularity (e.g. 15-min bars)
    — VWAP is not meaningful computed on daily bars.
    """
    typical_price = (intraday_df["high"] + intraday_df["low"] + intraday_df["close"]) / 3
    pv = typical_price * intraday_df["volume"]
    session = intraday_df.index.normalize()
    cum_pv = pv.groupby(session).cumsum()
    cum_vol = intraday_df["volume"].groupby(session).cumsum()
    return cum_pv / cum_vol


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Standard Supertrend: an ATR-band trend-follower that flips direction
    when price closes through the opposite band. Returns the line and a
    +1/-1 direction column; a direction change IS the trade signal in most
    published Supertrend strategies, not a threshold crossing."""
    hl2 = (df["high"] + df["low"]) / 2
    atr_val = atr(df, period)
    upper_basic = hl2 + multiplier * atr_val
    lower_basic = hl2 - multiplier * atr_val

    upper = upper_basic.copy()
    lower = lower_basic.copy()
    direction = pd.Series(1, index=df.index)
    close = df["close"]

    for i in range(1, len(df)):
        upper.iloc[i] = (
            upper_basic.iloc[i]
            if upper_basic.iloc[i] < upper.iloc[i - 1] or close.iloc[i - 1] > upper.iloc[i - 1]
            else upper.iloc[i - 1]
        )
        lower.iloc[i] = (
            lower_basic.iloc[i]
            if lower_basic.iloc[i] > lower.iloc[i - 1] or close.iloc[i - 1] < lower.iloc[i - 1]
            else lower.iloc[i - 1]
        )
        if close.iloc[i] > upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

    line = pd.Series(
        [lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i] for i in range(len(df))],
        index=df.index,
    )
    return pd.DataFrame({"line": line, "direction": direction})


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """Classic %K/%D stochastic oscillator over the close relative to the
    period's high-low range."""
    lowest_low = df["low"].rolling(k_period).min()
    highest_high = df["high"].rolling(k_period).max()
    percent_k = 100 * (df["close"] - lowest_low) / (highest_high - lowest_low)
    percent_d = percent_k.rolling(d_period).mean()
    return pd.DataFrame({"k": percent_k, "d": percent_d})
