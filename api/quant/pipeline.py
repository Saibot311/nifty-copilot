"""Ties the market-data abstraction to the indicator/regime/price-action
calculations and produces one plain-dict result the API can serialize.
This is the only place that decides "daily data for indicators, short
intraday data for VWAP" — a data-depth compromise forced by free data
(see docs/PROJECT_PLAN.md), not a permanent design decision.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from market_data import Candle, YFinanceProvider
from market_data.nse_indices import top_up as nse_top_up

from .indicators import atr, historical_volatility, relative_volume, rsi, session_vwap
from .price_action import evaluate as evaluate_price_action
from .regime import classify_regime


def _safe_round(value, digits: int = 2):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), digits)


def candles_to_df(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.model_dump() for c in candles])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp").sort_index()


def build_analysis(symbol: str = "^NSEI") -> dict:
    provider = YFinanceProvider()

    daily_candles = provider.get_ohlc(
        symbol, "1d", date.today() - timedelta(days=400), date.today()
    )
    if len(daily_candles) < 60:
        raise ValueError(
            f"Only got {len(daily_candles)} daily bars for {symbol} — need 60+ to compute indicators."
        )
    # Same top-up as the backtests: when Yahoo is a day late, NSE's own
    # index report has the close, and the dashboard should not show an
    # older session than the rest of the page.
    daily_df = nse_top_up(candles_to_df(daily_candles), symbol)

    regime_result = classify_regime(daily_df)
    price_action = evaluate_price_action(daily_df)

    close = daily_df["close"]
    rsi_val = rsi(close).iloc[-1]
    atr_val = atr(daily_df).iloc[-1]
    rel_vol_val = relative_volume(daily_df).iloc[-1]
    hist_vol_val = historical_volatility(close).iloc[-1]

    # True VWAP needs intraday bars. Yahoo Finance only gives ~60 days of
    # these for free — pull a short recent window just for this one number.
    vwap_reading = None
    try:
        intraday_candles = provider.get_ohlc(
            symbol, "15m", date.today() - timedelta(days=5), date.today()
        )
        if intraday_candles:
            intraday_df = candles_to_df(intraday_candles)
            vwap_series = session_vwap(intraday_df)
            latest_price = float(intraday_df["close"].iloc[-1])
            latest_vwap = float(vwap_series.iloc[-1])
            vwap_reading = {
                "value": _safe_round(latest_vwap),
                "price_vs_vwap_pct": _safe_round((latest_price - latest_vwap) / latest_vwap * 100),
            }
    except Exception:
        vwap_reading = None  # e.g. market closed today, no intraday bars yet — not fatal.

    snapshot_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    change = snapshot_price - prev_close
    change_pct = change / prev_close * 100

    india_vix = None
    try:
        vix_candles = provider.get_ohlc(
            "^INDIAVIX", "1d", date.today() - timedelta(days=10), date.today()
        )
        if vix_candles:
            india_vix = round(float(vix_candles[-1].close), 2)
    except Exception:
        india_vix = None

    return {
        "symbol": symbol,
        "as_of": daily_df.index[-1].isoformat(),
        "price": round(snapshot_price, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "regime": regime_result.regime,
        "indicators": {
            "ema_20": regime_result.ema_fast,
            "ema_50": regime_result.ema_slow,
            "adx_14": regime_result.adx_value,
            "rsi_14": _safe_round(rsi_val),
            "atr_14": _safe_round(atr_val),
            "historical_volatility_pct": _safe_round(hist_vol_val),
            "india_vix": india_vix,
            # NIFTY is a spot index — it has no real trading volume (only
            # its constituent stocks and derivatives do). Yahoo Finance
            # reports intraday volume as a flat 0 for ^NSEI, which makes
            # these two genuinely uncomputable from this free source —
            # not just imprecise. Flagged honestly rather than shown as a
            # real number. Real volume needs NIFTY futures data (Zerodha,
            # paid) — see Phase 7.
            "relative_volume": _safe_round(rel_vol_val),
            "relative_volume_reliable": False,
            "vwap": vwap_reading,
            "vwap_reliable": False,
        },
        "price_action": {
            "prev_day_high": price_action.prev_day_high,
            "prev_day_low": price_action.prev_day_low,
            "broke_prev_day_high": price_action.broke_prev_day_high,
            "broke_prev_day_low": price_action.broke_prev_day_low,
            "structure": price_action.structure,
        },
    }
