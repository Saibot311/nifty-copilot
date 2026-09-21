"""The implied-volatility research: the percentile must never look ahead,
the test must count each market day once, and the pre-registered
hypothesis must not be quietly edited after its result is known."""

import hashlib
import json

import pandas as pd
import pytest

import backtest.iv_research as ivr


def test_the_preregistered_test_has_not_been_edited():
    # Tripwire. The hypothesis and threshold were fixed and committed before
    # any result existed (commit d1aa408). Changing them after seeing the
    # answer turns a test into a fit. A different hypothesis is fine — as a
    # NEW test, with its own name in the hypothesis log — not as an edit.
    fixed = json.dumps({**ivr.PREREGISTERED, "threshold": ivr.IV_THRESHOLD_PCT,
                        "alpha": ivr.SIGNIFICANCE_ALPHA, "window": ivr.PCT_WINDOW}, sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH, (
        "The pre-registered IV test was edited. Register a new test instead.")


# A literal, taken when the test was registered. Computing it from the live
# constants would make this test pass whatever they were changed to.
PREREGISTERED_HASH = "03f1fb8314785631"


def test_the_percentile_never_looks_ahead(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "iv.db"
    conn = sqlite3.connect(db)
    conn.executescript(ivr.SCHEMA)
    days = pd.bdate_range("2020-01-01", periods=400)
    vals = [0.10 + 0.0003 * i for i in range(400)]
    conn.executemany("INSERT INTO iv_daily (trade_date, iv_30d) VALUES (?, ?)",
                     [(str(d.date()), v) for d, v in zip(days, vals)])
    conn.commit()
    monkeypatch.setattr(ivr, "IV_DB", db)
    full = ivr.load_series()["iv_pct"]
    # Wipe the second half and recompute: the first half must not change.
    conn.execute("DELETE FROM iv_daily WHERE trade_date > ?", (str(days[199].date()),))
    conn.commit()
    part = ivr.load_series()["iv_pct"]
    pd.testing.assert_series_equal(full.iloc[:200], part, check_names=False)
    # A steadily rising series is always at its own 100th percentile.
    assert full.iloc[-1] == 100


def test_no_percentile_before_half_a_year_of_history(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "iv.db"
    conn = sqlite3.connect(db)
    conn.executescript(ivr.SCHEMA)
    conn.executemany("INSERT INTO iv_daily (trade_date, iv_30d) VALUES (?, ?)",
                     [(str(d.date()), 0.12) for d in pd.bdate_range("2020-01-01", periods=200)])
    conn.commit()
    monkeypatch.setattr(ivr, "IV_DB", db)
    s = ivr.load_series()["iv_pct"]
    assert s.iloc[: ivr.PCT_MIN_HISTORY - 1].isna().all() and s.iloc[ivr.PCT_MIN_HISTORY - 1:].notna().all()


def _row(day, rupees, pct, exit_day=None, pattern="p"):
    return {"pattern": pattern, "entry_date": day, "exit_date": exit_day or day, "rupees": rupees, "iv_pct": pct}


def test_one_market_day_counts_once():
    # Three patterns bought on one day share one market: one observation.
    days = ivr._by_entry_date([_row("2024-03-01", 100, 30, pattern=x) for x in "abc"]
                              + [_row("2024-03-04", -50, 70)])
    assert len(days) == 2 and days["2024-03-01"]["rupees"] == 100


def test_a_development_trade_exiting_in_the_holdout_is_purged(monkeypatch):
    monkeypatch.setattr(ivr, "log_run", lambda *a, **k: None)
    rows = [_row(f"2022-0{m}-1{d}", 100 * d, 20, exit_day=f"2022-0{m}-2{d}") for m in range(1, 7) for d in range(5)]
    rows += [_row(f"2022-0{m}-0{d + 1}", -100, 80) for m in range(1, 7) for d in range(5)]
    rows.append(_row("2023-12-28", 10**7, 10, exit_day="2024-01-10"))  # would dominate if counted
    r = ivr.preregistered_test(rows)
    assert r["development"]["mean_low"] < 10**5


def test_verdict_requires_both_periods_and_significance(monkeypatch):
    monkeypatch.setattr(ivr, "log_run", lambda *a, **k: None)
    def rows_for(year, low_mean, high_mean, n=40):
        out = []
        for i in range(n):
            out.append(_row(f"{year}-{1 + i % 12:02d}-{1 + i % 28:02d}", low_mean + (i % 7) * 50, 20))
            out.append(_row(f"{year}-{1 + i % 12:02d}-{2 + i % 27:02d}", high_mean + (i % 5) * 50, 80))
        return out
    strong = ivr.preregistered_test(rows_for(2021, 3000, 0) + rows_for(2025, 3000, 0))
    assert strong["verdict"] == "CANDIDATE FILTER"
    flipped = ivr.preregistered_test(rows_for(2021, 3000, 0) + rows_for(2025, 0, 3000))
    assert flipped["verdict"] == "NOT ADOPTED"
