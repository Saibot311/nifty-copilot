"""The forward log is only worth anything if (1) it never records a verdict
from a still-forming bar, (2) a recorded verdict can never be rewritten,
and (3) outcomes use the same next-open execution as the backtester."""

from datetime import date, datetime

import pandas as pd
import pytest

from briefing.forward_log import bar_is_final, score
from market_data.kite_session import IST
from storage.forward_log_db import all_recommendations, record_recommendation


def test_todays_bar_is_not_final_until_the_close():
    today = date(2026, 9, 18)
    assert bar_is_final(today, datetime(2026, 9, 18, 11, 0, tzinfo=IST)) is False
    assert bar_is_final(today, datetime(2026, 9, 18, 15, 30, tzinfo=IST)) is True
    assert bar_is_final(date(2026, 9, 17), datetime(2026, 9, 18, 9, 0, tzinfo=IST)) is True


def _rec(as_of, action):
    return {"as_of": as_of, "action": action, "regime": "TREND_BULL", "headline": "h", "candidates": [], "evidence_bar": {}}


def test_a_recorded_day_can_never_be_overwritten(tmp_path):
    db = tmp_path / "fwd.db"
    assert record_recommendation(_rec("2026-09-17", "NO_TRADE"), 100.0, db_path=db) is True
    # A later recomputation that disagrees must not replace the original.
    assert record_recommendation(_rec("2026-09-17", "CONSIDER_CALL"), 105.0, db_path=db) is False
    rows = all_recommendations(db_path=db)
    assert len(rows) == 1 and rows[0]["action"] == "NO_TRADE" and rows[0]["close_as_of"] == 100.0


def test_outcomes_enter_at_next_open_and_respect_direction():
    idx = pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03"])
    df = pd.DataFrame({"open": [100, 200, 999], "close": [150, 210, 220]}, index=idx)

    call, put, fresh = score(
        [{"as_of": "2026-09-01", "action": "CONSIDER_CALL"}, {"as_of": "2026-09-01", "action": "CONSIDER_PUT"},
         {"as_of": "2026-09-03", "action": "NO_TRADE"}],
        df,
    )
    # Entry is 09-02's open (200), never 09-01's close (150).
    assert call["entry_open"] == 200
    assert call["outcomes"]["1d"] == {"index_move_pct": 5.0, "trade_return_pct": 5.0}
    assert put["outcomes"]["1d"]["trade_return_pct"] == -5.0
    # Horizons that haven't happened yet are absent, not guessed.
    assert "5d" not in call["outcomes"]
    assert fresh["outcomes"] == {}


def test_scored_actions_match_what_the_recommendation_actually_emits():
    # Caught while building this: the log was first written against "CALL"/"PUT",
    # which build_recommendation never emits, so no trade would ever have been scored.
    import inspect

    import briefing.recommendation as rec_module
    from briefing.forward_log import DIRECTION

    source = inspect.getsource(rec_module)
    for action in DIRECTION:
        assert f'"{action}"' in source


# --- a row written after its entry session opened is not forward evidence ----

SESSIONS = ["2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22"]


@pytest.mark.parametrize("as_of,when,late", [
    ("2026-09-17", "2026-09-17 19:30", False),   # the evening of the close: the normal path
    ("2026-09-17", "2026-09-18 09:14", False),   # next session not open yet
    ("2026-09-17", "2026-09-18 09:15", True),    # the entry price now exists
    ("2026-09-17", "2026-09-18 10:23", True),    # what actually happened to this row
    ("2026-09-18", "2026-09-19 12:00", False),   # Saturday: the next session is Monday
    ("2026-09-18", "2026-09-21 09:30", True),
    ("2026-09-22", "2026-09-22 17:51", False),   # no later session exists yet
])
def test_a_verdict_written_after_its_entry_session_opened_is_late(as_of, when, late):
    from briefing.forward_log import outcome_has_started
    now = datetime.fromisoformat(when).replace(tzinfo=IST)
    assert outcome_has_started(date.fromisoformat(as_of), SESSIONS, now) is late


def test_a_late_row_is_kept_but_never_counted():
    from briefing.forward_log import forward_report, recorded_late
    row = {"as_of": "2026-09-17", "recorded_at": "2026-09-18T04:53:25+00:00"}  # 10:23 IST on the 18th
    assert recorded_late(row, SESSIONS) is True
    on_time = {"as_of": "2026-09-17", "recorded_at": "2026-09-17T14:00:00+00:00"}  # 19:30 IST, same day
    assert recorded_late(on_time, SESSIONS) is False
    assert "days_excluded_recorded_late" in forward_report()["summary"]


def test_a_verdict_cannot_be_recorded_once_the_next_session_is_trading():
    """The next session is not in the daily data while it trades — Yahoo's
    bar arrives after the close. With no later session to look at, the check
    used to say "not started", so a verdict for Wednesday could be written at
    11:00 on Thursday, with Thursday's move already under way, and count as
    forward evidence. The calendar stands in for the missing session."""
    from datetime import date, datetime
    from briefing.forward_log import IST, outcome_has_started
    wed = date(2026, 9, 23)
    sessions = ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert outcome_has_started(wed, sessions, datetime(2026, 9, 24, 11, 0, tzinfo=IST)) is True
    assert outcome_has_started(wed, sessions, datetime(2026, 9, 24, 9, 0, tzinfo=IST)) is False
    assert outcome_has_started(wed, sessions, datetime(2026, 9, 23, 19, 30, tzinfo=IST)) is False
    fri = date(2026, 9, 25)
    fri_sessions = sessions + ["2026-09-24", "2026-09-25"]
    assert outcome_has_started(fri, fri_sessions, datetime(2026, 9, 26, 11, 0, tzinfo=IST)) is False  # Saturday
    assert outcome_has_started(fri, fri_sessions, datetime(2026, 9, 28, 9, 20, tzinfo=IST)) is True   # Monday
