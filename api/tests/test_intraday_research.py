"""Intraday studies. These test the system's execution assumption rather
than any pattern's edge, so the thing to guard is the discipline: entries
always land after the signal, and a result that flips sign between periods
is never reported as a finding."""

import pytest

import backtest.intraday as it


def _bars(prices: dict[str, float]) -> dict[str, dict]:
    return {t: {"open": p, "high": p, "low": p, "close": p} for t, p in prices.items()}


def _flat_day(price: float) -> dict[str, dict]:
    return _bars({t: price for t in it.ENTRIES.values()})


def _sessions(prices: list[float], start: int = 1) -> dict[str, dict]:
    return {f"2020-01-{start + i:02d}": _flat_day(p) for i, p in enumerate(prices)}


# --- loading -----------------------------------------------------------------

def test_short_sessions_are_dropped_not_padded(tmp_path):
    # Half-days and outage days have a different clock; averaging "when the
    # market moves" over them would compare different sessions.
    import sqlite3
    db = tmp_path / "bars.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE index_bars (symbol TEXT, interval TEXT, ts TEXT, open REAL, "
                 "high REAL, low REAL, close REAL, volume REAL, source TEXT)")
    rows = [("^NSEI", "15m", f"2020-01-01T{9 + i // 4:02d}:{15 * (i % 4):02d}:00+05:30", 1, 1, 1, 1, 0, "t")
            for i in range(25)]
    rows += [("^NSEI", "15m", f"2020-01-02T{9 + i // 4:02d}:{15 * (i % 4):02d}:00+05:30", 1, 1, 1, 1, 0, "t")
             for i in range(4)]
    conn.executemany("INSERT INTO index_bars VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()
    days = it.load_intraday("^NSEI", db_path=db)
    assert list(days) == ["2020-01-01"] and len(days["2020-01-01"]) == 25


def test_entry_price_is_the_start_of_its_bar_except_the_close():
    bars = _bars({"09:15": 100, "09:30": 110, "09:45": 120, "10:15": 130, "15:15": 140})
    assert it._entry_price(bars, "open") == 100
    assert it._entry_price(bars, "10:15") == 130
    assert it._entry_price(bars, "close") == 140  # the session's last print


# --- no look-ahead -----------------------------------------------------------

def test_entry_is_the_session_after_the_signal(monkeypatch):
    # Signal on day 0 at 100; day 1 at 200; days 2-5 at 400. Entering
    # correctly on day 1 doubles. Entering on the signal day would quadruple.
    intraday = _sessions([100, 200, 400, 400, 400, 400])
    monkeypatch.setattr(it, "HOLD_DAYS", (5,))
    monkeypatch.setattr(it, "MIN_TRADES", 1)
    monkeypatch.setattr(it, "STRATEGY_REGISTRY", {"fake": {"direction": "long"}})
    monkeypatch.setattr(it, "_signal_dates", lambda df, regime: {"fake": ["2020-01-01"]})
    out = it.entry_timing(intraday, None, None)["5d"]
    assert out["by_entry"]["open"]["dev"]["avg_pct"] == pytest.approx(100.0)


def test_a_signal_too_close_to_the_end_is_skipped(monkeypatch):
    intraday = _sessions([100, 200, 400])
    monkeypatch.setattr(it, "HOLD_DAYS", (5,))
    monkeypatch.setattr(it, "STRATEGY_REGISTRY", {"fake": {"direction": "long"}})
    monkeypatch.setattr(it, "_signal_dates", lambda df, regime: {"fake": ["2020-01-01"]})
    out = it.entry_timing(intraday, None, None)["5d"]
    assert out["by_entry"]["open"]["dev"]["trades"] == 0


# --- the baseline ------------------------------------------------------------

def test_long_and_short_see_the_same_drift_with_opposite_signs():
    # Entering later buys higher for a long and sells higher for a short.
    intraday = {"2020-01-01": _bars({"09:15": 100, "09:30": 101, "09:45": 101, "10:15": 101, "15:15": 101})}
    b = it._baselines(intraday, ["2020-01-01"])
    assert b[("long", "dev", "09:30")] == pytest.approx(-1.0)
    assert b[("short", "dev", "09:30")] == pytest.approx(1.0)


# --- verdicts ----------------------------------------------------------------

def _summary(dev_excess, dev_t, hold_excess, hold_t):
    row = {"dev": {"excess_pct": dev_excess, "excess_t": dev_t, "trades": 500},
           "holdout": {"excess_pct": hold_excess, "excess_t": hold_t, "trades": 200},
           "is_execution_choice": True}
    return {"09:45": row}


def test_a_sign_flip_between_periods_is_not_a_finding():
    # Found on real data: dev said waiting was worse (t=-4), the holdout said
    # better (t=+3.3). Two significant results pointing opposite ways measure
    # the period, not the execution.
    v = it._verdict(_summary(-0.03, -3.97, 0.041, 3.31), "09:45", 2528)
    assert v["verdict"] == "UNSTABLE — SIGN FLIPS BETWEEN PERIODS"
    assert "next-open rule stands" in v["detail"]


def test_an_effect_must_replicate_in_both_periods_to_count():
    v = it._verdict(_summary(0.05, 3.0, 0.04, 2.5), "09:45", 2528)
    assert v["verdict"] == "BETTER THAN THE OPEN"


def test_significant_on_the_holdout_alone_is_not_enough():
    v = it._verdict(_summary(0.05, 3.0, -0.01, -0.4), "09:45", 2528)
    assert v["verdict"] == "NO BETTER THAN THE OPEN"


def test_too_few_development_trades_gets_no_verdict():
    assert it._verdict(_summary(0.05, 3.0, 0.04, 2.5), "09:45", 5)["verdict"] == "NOT ENOUGH DATA"


# --- opening cost ------------------------------------------------------------

def test_a_drift_confined_to_one_period_is_not_called_stable():
    # Two years of drift and two without would pass a pooled t-test; the
    # per-year and per-period split is what stops it being reported.
    drifting = {f"2016-01-{i:02d}": _bars({**{t: 100 for t in it.ENTRIES.values()}, "09:15": 100})
                for i in range(1, 29)}
    for d in drifting:
        drifting[d]["09:15"] = {"open": 100, "high": 100, "low": 99, "close": 99}
    calm = {f"2025-01-{i:02d}": _bars({t: 100 for t in it.ENTRIES.values()}) for i in range(1, 29)}
    for d in calm:
        calm[d]["09:15"] = {"open": 100, "high": 100.5, "low": 99.5, "close": 100.5}
    r = it.opening_cost({**drifting, **calm})
    assert r["stable"] is False
    assert r["years_agreeing_with_the_mean"] == "1/2"
