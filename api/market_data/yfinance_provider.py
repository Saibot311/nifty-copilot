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


class YFinanceProvider:
    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> list[Candle]:
        interval = _INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"Unsupported timeframe '{timeframe}' for YFinanceProvider")

        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
        if df.empty:
            return []

        # yfinance returns MultiIndex columns when given a single ticker in
        # recent versions — flatten to plain column names.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

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
        return candles
