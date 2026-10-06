"""Every study reads its daily bars from Kite's archive first (the owner's
rule: Zerodha wherever Zerodha has it), Yahoo only when the archive holds too
little, so a night when Yahoo is down no longer stops the research."""

from datetime import date, timedelta

import pytest

import backtest.strategies as st
from market_data import Candle


def _candles(n, close=100.0):
    d0 = date.today() - timedelta(days=n + 5)
    return [Candle(timestamp=(d0 + timedelta(days=i)).isoformat(), open=close, high=close + 1, low=close - 1,
                   close=close, volume=0) for i in range(n)]


@pytest.fixture
def sources(monkeypatch):
    asked = []

    class Archive:
        def get_ohlc(self, symbol, tf, start, end):
            asked.append("archive")
            return _candles(300, 100.0) if symbol == "^NSEI" else []

    class Yahoo:
        def get_ohlc(self, symbol, tf, start, end):
            asked.append("yahoo")
            return _candles(300, 200.0)
    monkeypatch.setattr("market_data.bar_archive.ArchiveProvider", Archive)
    monkeypatch.setattr(st, "YFinanceProvider", Yahoo)
    monkeypatch.setattr(st, "_top_up_from_nse", lambda df, symbol: df)
    return asked


def test_nifty_comes_from_the_kite_archive_and_yahoo_is_not_asked(sources):
    df, _ = st.load_daily_data("^NSEI")
    assert sources == ["archive"] and float(df["close"].iloc[-1]) == 100.0


def test_an_index_the_archive_lacks_falls_back_to_yahoo(sources):
    df, _ = st.load_daily_data("^NSEBANK")
    assert sources == ["archive", "yahoo"] and float(df["close"].iloc[-1]) == 200.0
