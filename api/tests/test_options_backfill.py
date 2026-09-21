"""The options backfill has to tell a holiday from a failed download. It
used to record every empty day as done, so a day fetched before its
bhavcopy was published — 2026-09-15, fetched at 13:38 IST — was skipped
forever."""

import importlib.util
from datetime import date
from pathlib import Path

import pytest

import storage.options_db as odb

spec = importlib.util.spec_from_file_location(
    "backfill_options", Path(__file__).parent.parent / "scripts" / "backfill_options.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)

TUE, WED, SAT, SUN = date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 19), date(2026, 2, 1)
SESSIONS = {"2026-09-15", "2026-02-01"}  # a Tuesday, and a Sunday Budget session


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "options.db"
    odb.init_db(path)
    monkeypatch.setattr(odb, "DB_PATH", path)
    saved = []
    real = odb.save_day
    monkeypatch.setattr(bf, "save_day", lambda d, bars, confirmed_holiday=False: saved.append(
        (d, len(bars), confirmed_holiday)) or real(d, bars, path, confirmed_holiday))
    return path, saved


def test_an_empty_bhavcopy_on_a_session_is_a_failure_to_retry(db, monkeypatch):
    path, saved = db
    monkeypatch.setattr(bf, "fetch_option_bars", lambda day, symbol: [])
    assert bf.fetch_day(TUE, SESSIONS, "2026-09-18", "NIFTY") == "failed"
    assert not odb.is_day_ingested("2026-09-15", path)


def test_an_empty_day_the_index_did_not_trade_is_a_holiday(db, monkeypatch):
    path, _ = db
    monkeypatch.setattr(bf, "fetch_option_bars", lambda day, symbol: [])
    assert bf.fetch_day(WED, SESSIONS, "2026-09-18", "NIFTY") == "holiday"
    assert odb.is_day_ingested("2026-09-16", path)


def test_an_empty_day_beyond_the_index_archive_is_left_open(db, monkeypatch):
    path, _ = db
    monkeypatch.setattr(bf, "fetch_option_bars", lambda day, symbol: [])
    assert bf.fetch_day(WED, SESSIONS, "2026-09-10", "NIFTY") == "unknown"
    assert not odb.is_day_ingested("2026-09-16", path)


def test_a_weekend_session_is_fetched_and_a_plain_weekend_is_not(db, monkeypatch):
    asked = []
    monkeypatch.setattr(bf, "fetch_option_bars", lambda day, symbol: asked.append(day) or [])
    assert bf.fetch_day(SAT, SESSIONS, "2026-09-18", "NIFTY") == "skipped"
    bf.fetch_day(SUN, SESSIONS, "2026-09-18", "NIFTY")
    assert asked == [SUN]


def test_save_day_will_not_mark_an_empty_day_on_its_own(tmp_path):
    path = tmp_path / "o.db"
    odb.init_db(path)
    assert odb.save_day("2026-09-15", [], path) == 0
    assert not odb.is_day_ingested("2026-09-15", path)
    odb.save_day("2026-09-16", [], path, confirmed_holiday=True)
    assert odb.is_day_ingested("2026-09-16", path)
