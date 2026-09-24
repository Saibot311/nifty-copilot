import threading
import time
from datetime import date

import pandas as pd
import yfinance as yf

from .base import Candle

# Free, no signup, no API key. Real data, but limited depth/granularity:
# daily bars go back years; intraday (e.g. "15m") is only available for
# roughly the last 60 days on Yahoo Finance. Good enough to prove the
# pipeline works — not a substitute for a real historical data source
# once Phase 7 needs 10 years of 15-minute bars.
_INTERVAL_MAP = {
    "1d": "1d",
    "1h": "60m",
    "15m": "15m",
    "5m": "5m",
}

# The dashboard's one page load fires off several independent API calls
# (snapshot, indicators, backtest, two research endpoints) that all end up
# wanting the same underlying daily bars. Without this, that's 5 redundant
# network round-trips to Yahoo Finance per page view — slow, and under
# concurrent load prone to timing out. A short in-memory cache means one
# real fetch serves all of them; 60s is short enough that live-ish data
# still updates promptly once markets are actually being watched.
_CACHE: dict[tuple, tuple[float, list[Candle]]] = {}
_CACHE_TTL_SECONDS = 60

# yfinance writes a local cache file for cookie/timezone data as a side
# effect of every call. Two threads calling it at the same instant (which
# happens routinely here — one dashboard page load fires off 5 independent
# API requests, and FastAPI runs sync endpoints in a thread pool) can
# corrupt each other's writes to that file, surfacing as a confusing
# "Extra data" JSON parse error with no obvious connection to the real
# cause. A single lock around the actual download serializes access and
# eliminates the race outright — simpler and more robust than trying to
# reconfigure yfinance's internal cache.
_FETCH_LOCK = threading.Lock()

# One HTTP session for every Yahoo call, reused through Ticker.history.
# `yf.download` opened a fresh connection (and a pipe pair) per call and never
# closed it — 40 fetches left 40 sockets open, which garbage collection did
# not free. Under launchd the API may hold 256 files, so a dashboard left open
# through a session ran it out of descriptors, and every request that touches
# a file began to fail while /health, which touches none, kept answering.
_SESSION = None


def _session():
    global _SESSION
    if _SESSION is None:
        from curl_cffi import requests as curl_requests

        _SESSION = curl_requests.Session(impersonate="chrome")
    return _SESSION


class YFinanceProvider:
    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> list[Candle]:
        interval = _INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"Unsupported timeframe '{timeframe}' for YFinanceProvider")

        cache_key = (symbol, interval, start.isoformat(), end.isoformat())

        with _FETCH_LOCK:
            # Re-check inside the lock: another thread may have just
            # populated the cache while we were waiting for it.
            cached = _CACHE.get(cache_key)
            if cached and (time.monotonic() - cached[0]) < _CACHE_TTL_SECONDS:
                return cached[1]

            df = yf.Ticker(symbol, session=_session()).history(
                start=start.isoformat(),
                end=end.isoformat(),
                interval=interval,
                auto_adjust=False,
                actions=False,
            )
            if df.empty:
                return []
            # history() dates daily bars in the exchange's zone; download()
            # did not. Keep the plain dates every consumer was built on.
            if interval == "1d" and df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            # yfinance returns MultiIndex columns when given a single ticker
            # in recent versions — flatten to plain column names.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Yahoo includes a placeholder row for the most recent session
            # before it's actually settled: open/high/low present, but
            # close=NaN and volume=0. Treating that as a real candle would
            # be exactly the kind of "unfinished bar" data-integrity issue
            # this project is built to avoid — drop it rather than pass a
            # NaN price downstream.
            df = df.dropna(subset=["Close"])
            if df.empty:
                return []

            candles = []
            for ts, row in df.iterrows():
                candles.append(
                    Candle(
                        timestamp=ts.isoformat(),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]) if "Volume" in row else None,
                    )
                )
            _CACHE[cache_key] = (time.monotonic(), candles)
            return candles
