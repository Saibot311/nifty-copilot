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
from market_data.zerodha_provider import ZerodhaProvider

from .indicators import atr, ema, historical_volatility, relative_volume, rsi
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


def _india_vix(provider) -> dict:
    """India VIX, from NSE's own feed first: live during a session, the close
    after it. Then Kite's, the same figure through the logged-in session.
    Yahoo's daily ^INDIAVIX lags and drops sessions — it showed 10.35 from
    23 Sep 2026 while NSE's close on the 24th was 12.7, with no date beside
    it — so it is only the last resort, and it says its date."""
    try:
        from market_data.live_quote import live_index_quote
        q = live_index_quote()
        if q.get("india_vix") is not None:
            return {"value": round(float(q["india_vix"]), 2), "source": "NSE",
                    "as_of": q.get("market_time") or q.get("fetched_at")}
    except Exception:
        pass
    try:
        candles = ZerodhaProvider().get_ohlc("^INDIAVIX", "1d", date.today() - timedelta(days=10), date.today())
        if candles:
            c = candles[-1]
            # Kite's bar for a session in progress follows the index.
            return {"value": round(float(c.close), 2), "source": "Kite" if c.provisional else "Kite daily",
                    "as_of": c.timestamp[:10]}
    except Exception:
        pass
    try:
        candles = provider.get_ohlc("^INDIAVIX", "1d", date.today() - timedelta(days=10), date.today())
        if candles:
            return {"value": round(float(candles[-1].close), 2), "source": "Yahoo daily",
                    "as_of": candles[-1].timestamp[:10]}
    except Exception:
        pass
    return {"value": None, "source": None, "as_of": None}


KITE_SOURCE = "Kite daily (NSE's own figures)"
YAHOO_SOURCE = "Yahoo daily, with missing or late sessions filled from NSE's index report"


def daily_frame(symbol: str = "^NSEI", days: int = 400) -> pd.DataFrame:
    """The daily series the indicator grid and the Today chart both read:
    the completed sessions. Kite first: its daily closes are NSE's on every
    one of 2,194 sessions checked, with none missing or a day late. Yahoo,
    with sessions it is missing or late with filled from NSE's own index
    report, only when the Kite login has lapsed. `attrs["source"]` says which."""
    start = date.today() - timedelta(days=days)
    try:
        done = [c for c in ZerodhaProvider().get_ohlc(symbol, "1d", start, date.today()) if not c.provisional]
        if len(done) >= 60:
            df = candles_to_df(done)
            df.attrs["source"] = KITE_SOURCE
            return df
    except Exception:
        pass
    candles = YFinanceProvider().get_ohlc(symbol, "1d", start, date.today())
    if len(candles) < 60:
        raise ValueError(f"Only got {len(candles)} daily bars for {symbol} — need 60+ to compute indicators.")
    df = nse_top_up(candles_to_df(candles), symbol)
    df.attrs["source"] = YAHOO_SOURCE
    return df


def chart_series(symbol: str = "^NSEI", sessions: int = 110) -> dict:
    """The Today chart: the last `sessions` daily candles with EMA20/EMA50.
    The same series and the same EMA function as the indicator grid, over the
    same full history — so the lines on the chart are the numbers printed
    beside it. Computed here, not in the browser (I2): it used to compute
    them from the bars on screen, which neither matched the grid nor gave the
    EMA50 a value before the chart's halfway point."""
    df = daily_frame(symbol)
    if "provisional" in df.columns:
        df = df[~df["provisional"].astype(bool)]
    e20, e50 = ema(df["close"], 20), ema(df["close"], 50)
    tail = df.tail(sessions)
    return {
        "as_of": str(tail.index[-1].date()),
        "sessions": len(tail),
        "source": df.attrs.get("source", YAHOO_SOURCE),
        "candles": [{"date": str(ts.date()), "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
                     "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
                     "ema20": round(float(e20.loc[ts]), 2), "ema50": round(float(e50.loc[ts]), 2)}
                    for ts, r in tail.iterrows()],
    }


def build_analysis(symbol: str = "^NSEI") -> dict:
    provider = YFinanceProvider()
    daily_df = daily_frame(symbol)

    regime_result = classify_regime(daily_df)
    price_action = evaluate_price_action(daily_df)

    close = daily_df["close"]
    rsi_val = rsi(close).iloc[-1]
    atr_val = atr(daily_df).iloc[-1]
    rel_vol_val = relative_volume(daily_df).iloc[-1]
    hist_vol_val = historical_volatility(close).iloc[-1]

    # VWAP needs volume, and a spot index has none: Kite and Yahoo both give
    # NIFTY's bars a volume of 0 (checked 28 Sep 2026), so it cannot be
    # computed from either. It is not fetched; real volume would have to come
    # from NIFTY futures.
    vwap_reading = None

    snapshot_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    change = snapshot_price - prev_close
    change_pct = change / prev_close * 100

    vix = _india_vix(provider)

    return {
        "symbol": symbol,
        "as_of": daily_df.index[-1].isoformat(),
        "source": daily_df.attrs.get("source", YAHOO_SOURCE),
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
            "india_vix": vix["value"],
            "india_vix_source": vix["source"],
            "india_vix_as_of": vix["as_of"],
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
