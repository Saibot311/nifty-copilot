"""Phase 1 of the strategy pipeline: which option a buyer should hold. What
must hold: development data only (no exit in 2024 or later); the expiry
outlasts the hold; "monthly" is the last expiry of its month; the measure is
the cost per point of exposure, calls and puts weighted equally."""

import sqlite3

import pytest

import backtest.instrument_study as ins


def test_delta_is_the_black_scholes_delta_for_both_sides():
    assert round(ins.delta("CE", 100, 100, 7 / 365, 0.15), 2) == 0.50
    assert round(ins.delta("PE", 100, 100, 7 / 365, 0.15), 2) == 0.50
    assert ins.delta("PE", 100, 99, 7 / 365, 0.15) < 0.5 < ins.delta("PE", 100, 101, 7 / 365, 0.15)


@pytest.fixture
def archive(tmp_path):
    """Two sessions of a toy archive: a weekly expiring the next day, a later
    weekly, and a monthly; plus a 2024 session the study must never reach."""
    opts, iv = tmp_path / "o.db", tmp_path / "iv.db"
    c = sqlite3.connect(opts)
    c.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, "
              "close REAL, contracts REAL, open_interest REAL)")
    rows = []
    for day, ce, pe in (("2023-12-27", 100.0, 100.0), ("2023-12-28", 120.0, 85.0), ("2024-01-01", 50.0, 50.0)):
        for exp in ("2023-12-28", "2024-01-04", "2024-01-25"):
            for k in (21700.0, 21800.0, 21900.0):
                rows += [(day, exp, k, "CE", ce, 10, 5000), (day, exp, k, "PE", pe, 10, 5000)]
    c.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?,?,?)", rows)
    c.commit(); c.close()
    v = sqlite3.connect(iv)
    v.execute("CREATE TABLE iv_daily (trade_date TEXT, iv_30d REAL)")
    v.executemany("INSERT INTO iv_daily VALUES (?, ?)", [("2023-12-27", 0.12), ("2023-12-28", 0.12)])
    v.commit(); v.close()
    return ins.Archive(opts, iv)


def test_the_expiry_outlasts_the_hold_and_monthly_is_the_last_of_its_month(archive):
    near = ins.pick(archive, "2023-12-27", 21800, "CE", 0.0, "nearest", "2023-12-28")
    assert near[0] == "2024-01-04"                        # not the one expiring on the exit day
    monthly = ins.pick(archive, "2023-12-27", 21800, "CE", 0.0, "monthly", "2023-12-28")
    assert monthly[0] == "2024-01-25" and "2024-01-25" in archive.monthly


def test_the_study_never_reaches_2024(archive, monkeypatch):
    monkeypatch.setattr(ins, "START", "2023-12-27")
    r = ins.run_instrument_study(archive, {"2023-12-27": 21800.0, "2023-12-28": 21850.0, "2024-01-01": 21000.0},
                                 sensitivity=False)
    assert r["period"]["to"] == "2023-12-28" and r["period"]["sessions"] == 2
    atm1 = [c for c in r["cells"] if c["moneyness"] == "ATM" and c["hold"] == 1 and c["expiry"] == "nearest"][0]
    assert atm1["trades"] == 2                            # one call, one put; the 2024 session never priced


def test_the_carry_weighs_calls_and_puts_equally_so_drift_cancels():
    call = {"kind": "CE", "carry_pts": -10.0, "net_pct": 20.0, "cost_pct": 3.0, "days_to_expiry": 7}
    put = {"kind": "PE", "carry_pts": 30.0, "net_pct": -30.0, "cost_pct": 3.0, "days_to_expiry": 7}
    cell = ins._cell([call, put, put])                    # twice as many puts must not tilt it
    assert cell["carry_pts_per_session"] == 10.0 and cell["net_pct"] == -5.0
