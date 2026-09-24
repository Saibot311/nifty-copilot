"""The Yahoo provider must not leak a connection per call.

`yf.download` opened a new connection (and a pipe pair) on every call and
never closed it: 40 fetches left 40 sockets open, which garbage collection
did not free. The API runs under launchd with a 256 open-file limit, so a
dashboard left open through a session would eventually fail every request
that touches a file — while /health, which touches none, kept answering.
One shared session, reused through `Ticker.history`, holds the count flat.
"""

import pandas as pd
import pytest

import market_data.yfinance_provider as yp
from datetime import date


class _FakeTicker:
    sessions: list = []

    def __init__(self, symbol, session=None):
        _FakeTicker.sessions.append(session)

    def history(self, start, end, interval, auto_adjust, actions=True):
        idx = pd.DatetimeIndex(["2026-09-22", "2026-09-23"]).tz_localize("Asia/Kolkata")
        return pd.DataFrame({"Open": [1.0, 2.0], "High": [2.0, 3.0], "Low": [0.5, 1.5],
                             "Close": [1.5, 2.5], "Volume": [0.0, 0.0]}, index=idx)


@pytest.fixture
def fake_yahoo(monkeypatch):
    _FakeTicker.sessions = []
    monkeypatch.setattr(yp.yf, "Ticker", _FakeTicker)
    monkeypatch.setattr(yp.yf, "download", lambda *a, **k: pytest.fail("yf.download leaks a socket per call"))
    monkeypatch.setattr(yp, "_CACHE", {})
    return _FakeTicker


def test_every_fetch_reuses_one_session(fake_yahoo):
    p = yp.YFinanceProvider()
    p.get_ohlc("^NSEI", "1d", date(2026, 1, 1), date(2026, 9, 24))
    p.get_ohlc("^NSEI", "1d", date(2025, 1, 1), date(2026, 9, 24))  # a different key: a real second fetch
    assert len(fake_yahoo.sessions) == 2 and fake_yahoo.sessions[0] is fake_yahoo.sessions[1] is not None


def test_daily_bars_keep_the_plain_date_timestamps_they_always_had(fake_yahoo):
    candles = yp.YFinanceProvider().get_ohlc("^NSEI", "1d", date(2026, 9, 1), date(2026, 9, 24))
    assert [c.timestamp for c in candles] == ["2026-09-22T00:00:00", "2026-09-23T00:00:00"]
