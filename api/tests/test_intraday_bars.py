"""A still-forming bar used as if it were final is a look-ahead bug: its
close is just the latest tick. These lock down when a bar counts as final,
and that the archive never stores one that isn't."""

from datetime import date, datetime

from market_data.bar_archive import ArchiveProvider, last_timestamp, save_bars
from market_data.base import Candle
from market_data.kite_session import IST
from market_data.zerodha_provider import is_provisional


def _ist(h, m, day=18):
    return datetime(2026, 9, day, h, m, tzinfo=IST)


def test_bar_is_provisional_until_its_window_closes():
    bar = _ist(9, 45)
    assert is_provisional(bar, "15minute", now=_ist(9, 57)) is True
    assert is_provisional(bar, "15minute", now=_ist(9, 59)) is True
    assert is_provisional(bar, "15minute", now=_ist(10, 0)) is False


def test_last_bar_of_session_closes_at_market_close():
    # 60-minute bars start at 15:15 but the session ends at 15:30.
    assert is_provisional(_ist(15, 15), "60minute", now=_ist(15, 30)) is False
    assert is_provisional(_ist(15, 15), "60minute", now=_ist(15, 29)) is True


def test_bar_after_regular_close_is_not_instantly_final():
    # Diwali Muhurat session bars start at 18:15 — found in the real archive.
    muhurat = _ist(18, 15)
    assert is_provisional(muhurat, "15minute", now=_ist(18, 20)) is True
    assert is_provisional(muhurat, "15minute", now=_ist(18, 30)) is False


def test_daily_bar_is_provisional_until_the_close():
    today = datetime(2026, 9, 18, tzinfo=IST)
    assert is_provisional(today, "day", now=_ist(14, 0)) is True
    assert is_provisional(today, "day", now=_ist(15, 30)) is False
    assert is_provisional(datetime(2026, 9, 17, tzinfo=IST), "day", now=_ist(9, 20)) is False


def _candle(ts, close, provisional=False):
    return Candle(timestamp=ts, open=close, high=close, low=close, close=close, volume=0, provisional=provisional)


def test_archive_never_stores_provisional_bars(tmp_path):
    db = tmp_path / "bars.db"
    bars = [
        _candle("2026-09-18T09:15:00+05:30", 100),
        _candle("2026-09-18T09:30:00+05:30", 101),
        _candle("2026-09-18T09:45:00+05:30", 102, provisional=True),
    ]
    assert save_bars("^NSEI", "15m", bars, source="test", db_path=db) == 2
    assert last_timestamp("^NSEI", "15m", db_path=db) == "2026-09-18T09:30:00+05:30"


def test_archive_provider_round_trip_and_upsert(tmp_path):
    db = tmp_path / "bars.db"
    save_bars("^NSEI", "15m", [_candle("2026-09-17T09:15:00+05:30", 100)], source="test", db_path=db)
    # Re-running a backfill over the same day must replace, not duplicate.
    save_bars("^NSEI", "15m", [_candle("2026-09-17T09:15:00+05:30", 100)], source="test", db_path=db)
    save_bars("^NSEI", "15m", [_candle("2026-09-18T09:15:00+05:30", 105)], source="test", db_path=db)

    got = ArchiveProvider(db).get_ohlc("^NSEI", "15m", date(2026, 9, 17), date(2026, 9, 17))
    assert [c.close for c in got] == [100]
    both = ArchiveProvider(db).get_ohlc("^NSEI", "15m", date(2026, 9, 17), date(2026, 9, 18))
    assert len(both) == 2


def test_a_bad_tick_beyond_the_days_range_is_clamped():
    # The real case: 2022-03-07 10:00 — open, low and close 15,785.4, high
    # 16,174.45, 230 points above the day's official high of 15,944.6.
    from market_data.bar_archive import clamp_to_daily
    assert clamp_to_daily(16174.45, 15785.4, 15785.4, 15785.4, 15944.6, 15711.45) == (15944.6, 15785.4)


def test_clamping_never_puts_open_or_close_outside_the_bar():
    from market_data.bar_archive import clamp_to_daily
    hi, lo = clamp_to_daily(110, 90, 105, 95, 100, 92)
    assert hi >= 105 and lo <= 95


def test_an_ordinary_bar_is_untouched():
    from market_data.bar_archive import clamp_to_daily
    assert clamp_to_daily(101, 99, 100, 100.5, 105, 95) == (101, 99)
