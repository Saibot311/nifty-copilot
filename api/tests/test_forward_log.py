"""The forward log is only worth anything if (1) it never records a verdict
from a still-forming bar, (2) a recorded verdict can never be rewritten,
and (3) outcomes use the same next-open execution as the backtester."""

from datetime import date, datetime

import pandas as pd

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
