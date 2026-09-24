"""News: the archive, the session clock, and the one thing that would make
the tone study worthless — using a day's own coverage to trade that day.

Much of any session's Indian market reporting is *about* that session's
move. A test that let tone from day D inform a trade on day D would be
measuring its own reflection and would look wonderful, so the alignment
rule gets more tests here than anything else.
"""

import hashlib
import json
from datetime import datetime

import pandas as pd
import pytest

import backtest.news_research as nr
from storage import news_db
from storage.news_db import IST


# --- the pre-registration ------------------------------------------------------

PREREGISTERED_HASH = "65a9d9f239e87059"  # a literal: computing it live would pass any edit


def test_the_preregistration_has_not_been_edited():
    """Fixed before any of the five had been computed. A changed idea is a
    new test with a new name, not an edit of this one."""
    fixed = json.dumps({**nr.PREREGISTERED, "tests": nr.TESTS_IN_FAMILY,
                        "min_holdout": nr.MIN_HOLDOUT_TRADES, "min_dte": nr.MIN_DTE,
                        "extreme_pct": nr.EXTREME_PCT, "trailing": nr.TRAILING_DAYS},
                       sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH


def test_the_gdelt_query_is_frozen():
    """A reworded query after seeing a result is the same sin as retuning a
    pattern's parameters. A new query is a new key, stored beside the old."""
    from market_data.gdelt import QUERIES, QUERY_SET

    assert QUERY_SET == "india_equities_v1"
    assert QUERIES[QUERY_SET] == '(nifty OR sensex OR "indian stock market") sourcecountry:india'


def test_every_hypothesis_buys_one_side_only():
    for name, spec in nr.PREREGISTERED["hypotheses"].items():
        assert spec["leg"] in ("CE", "PE"), name
        assert isinstance(spec["hold_sessions"], int) and spec["hold_sessions"] > 0, name


# --- the alignment rule, which is the whole ballgame ---------------------------

def test_a_threshold_never_sees_the_day_it_judges():
    """The percentile is built from days strictly before the signal day. If
    the day helped set its own threshold, an extreme day could qualify as
    extreme partly because of itself."""
    s = pd.Series(range(300), index=[f"d{i:03d}" for i in range(300)], dtype=float)
    hits = nr._trailing_extreme(s, "high", pct=10, trailing=252)
    # A monotonically rising series: every day past the warm-up is above the
    # trailing 90th percentile, and none before it can be.
    assert hits, "a rising series should trigger the high extreme"
    assert all(int(d[1:]) >= 252 for d in hits), "fired before the trailing window was full"


def test_nothing_fires_before_the_trailing_window_is_full():
    s = pd.Series(range(100), index=[f"d{i:03d}" for i in range(100)], dtype=float)
    assert nr._trailing_extreme(s, "low", trailing=252) == []


def test_the_entry_is_the_session_after_the_signal():
    """The look-ahead rule in one line: run_options_backtest enters at the
    close of the session AFTER the signal date, so a signal read off a
    completed UTC day is priced a full session later."""
    import inspect

    from backtest.options_engine import run_options_backtest

    src = inspect.getsource(run_options_backtest)
    assert "entry_date = trading_days[i + 1]" in src


# --- the session clock ---------------------------------------------------------

@pytest.mark.parametrize("clock,session,phase", [
    ("2026-09-24T08:30", "2026-09-24", "pre_open"),    # before the bell
    ("2026-09-24T09:20", "2026-09-24", "live"),
    ("2026-09-24T15:29", "2026-09-24", "live"),
    ("2026-09-24T16:45", "2026-09-25", "pre_open"),    # after the close is tomorrow's news
    ("2026-09-24T23:10", "2026-09-25", "pre_open"),
])
def test_a_headline_is_filed_against_the_session_that_can_act_on_it(clock, session, phase):
    seen = datetime.fromisoformat(clock).replace(tzinfo=IST)
    assert news_db.session_and_phase(seen) == (session, phase)


# --- the archive ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_news(tmp_path, monkeypatch):
    monkeypatch.setattr(news_db, "DB_PATH", tmp_path / "news.db")


def _item(title="RBI holds the repo rate", url="https://example.test/1"):
    return {"title": title, "summary": "", "url": url, "published_at": None,
            "source": "rbi", "source_name": "RBI press releases", "tier": 1}


def test_a_headline_keeps_the_moment_it_was_first_seen():
    """The research clock. Re-reading a feed every three minutes must not
    restamp a headline into a later session than the one it arrived in."""
    first = datetime(2026, 9, 24, 8, 30, tzinfo=IST)
    later = datetime(2026, 9, 24, 16, 0, tzinfo=IST)
    assert news_db.save_many([_item()], now=first) == 1
    assert news_db.save_many([_item()], now=later) == 0  # already known
    rows = news_db.recent()
    assert len(rows) == 1
    assert rows[0]["first_seen"].startswith("2026-09-24T08:30")
    assert rows[0]["session_date"] == "2026-09-24" and rows[0]["phase"] == "pre_open"


def test_an_unjudged_headline_is_unjudged_and_not_neutral():
    """'No opinion yet' and 'judged to be nothing' are different facts, and
    a zero in place of a null would quietly turn one into the other."""
    news_db.save_many([_item()], now=datetime(2026, 9, 24, 8, 30, tzinfo=IST))
    row = news_db.recent()[0]
    assert row["market_moving"] is None and row["direction"] is None


def test_a_judgment_is_stored_against_the_question_that_produced_it():
    now = datetime(2026, 9, 24, 8, 30, tzinfo=IST)
    news_db.save_many([_item()], now=now)
    hid = news_db.recent()[0]["id"]
    news_db.save_judgment(hid, "news_v1", {"market_moving": 0.96, "direction": "unclear",
                                           "dir_conf": 0.42, "topic": "policy"}, now=now)
    row = news_db.recent()[0]
    assert row["market_moving"] == 0.96 and row["topic"] == "policy"
    assert news_db.unjudged("news_v1") == []
    # A reworded question set has not judged it, so it is pending again
    # rather than inheriting the old answer.
    assert len(news_db.unjudged("news_v2")) == 1


def test_the_same_story_from_two_publishers_is_stored_once():
    from market_data.news import fetch_all

    a = _item(url="https://a.test/x")
    b = {**_item(url="https://b.test/y"), "source": "et_markets", "source_name": "ET"}
    now = datetime(2026, 9, 24, 8, 30, tzinfo=IST)
    news_db.save_many([a], now=now)
    # Different URLs, so both are stored — dedupe by title happens in the
    # fetcher, before anything reaches the archive.
    assert news_db.save_many([b], now=now) == 1
    assert fetch_all.__doc__ and "deduplicated" in fetch_all.__doc__


def test_sources_are_a_closed_list_of_dated_publishers():
    from market_data.news import SOURCES

    assert "moneycontrol" not in SOURCES, "its feeds stopped updating in April 2024"
    assert SOURCES["rbi"]["tier"] == 1
    for key, src in SOURCES.items():
        assert src["url"].startswith("https://"), key


def test_a_session_recap_does_not_count_as_a_market_moving_event():
    """Jev scored "Sensex, Nifty rebound in early trade" at 0.71 moving and
    topic 'noise' — right twice. A recap describes a move that has already
    happened; counting it would put the session's own reflection in the
    tally the reader is looking at."""
    from news.feed import is_moving

    recap = {"market_moving": 0.71, "topic": "noise"}
    event = {"market_moving": 0.71, "topic": "commodity_currency"}
    weak = {"market_moving": 0.2, "topic": "policy"}
    unread = {"market_moving": None, "topic": None}
    assert not is_moving(recap)
    assert is_moving(event)
    assert not is_moving(weak)
    assert not is_moving(unread)
