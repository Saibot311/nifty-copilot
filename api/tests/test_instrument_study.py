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


SPOTS = {"2023-12-27": 21800.0, "2023-12-28": 21850.0, "2024-01-01": 21000.0}
# The hold-1 carry on the toy archive, recorded before costs_for existed: the
# default path must keep giving exactly these.
GOLDEN_CARRY = {("nearest", "1% OTM"): 4.04, ("nearest", "ATM"): 3.15, ("nearest", "1% ITM"): 2.58,
                ("monthly", "1% OTM"): 3.84, ("monthly", "ATM"): 3.37, ("monthly", "1% ITM"): 3.0}


def test_the_default_path_is_unchanged_by_per_cell_costs(archive, monkeypatch):
    monkeypatch.setattr(ins, "START", "2023-12-27")
    default = ins.run_instrument_study(archive, SPOTS)
    for c in default["cells"]:
        if c["hold"] == 1:
            assert c["carry_pts_per_session"] == GOLDEN_CARRY[(c["expiry"], c["moneyness"])]
            assert (c["trades"], c["net_pct"], c["cost_pct"], c["median_net_pct"]) == (2, -1.45, 3.95, -1.45)
        else:
            assert c == {"expiry": c["expiry"], "moneyness": c["moneyness"], "hold": c["hold"], "trades": 0}
    assert default["choices"]["directional"] == {"expiry": "nearest", "moneyness": "1% ITM"}
    assert default["choices"]["event_straddle"] == {"expiry": "nearest", "hold": 1}
    same = ins.run_instrument_study(archive, SPOTS, costs_for=lambda choice, label: ins.COSTS)
    assert same == default


def test_costs_for_prices_each_cell_with_its_own_model(archive, monkeypatch):
    monkeypatch.setattr(ins, "START", "2023-12-27")
    asked = set()

    def costs_for(choice, label):
        asked.add((choice, label))
        return ins.OptionsCostModel(premium_slippage_pct=0.05 if choice == "monthly" else 0.0)

    r = ins.run_instrument_study(archive, SPOTS, sensitivity=False, costs_for=costs_for)
    assert asked == set(GOLDEN_CARRY)
    base = ins.run_instrument_study(archive, SPOTS, ins.OptionsCostModel(premium_slippage_pct=0.0), False)

    def atm1(res, expiry):
        return [c for c in res["cells"] if c["expiry"] == expiry and c["moneyness"] == "ATM" and c["hold"] == 1][0]
    assert atm1(r, "nearest") == atm1(base, "nearest")      # zero slippage: as the plain zero-slippage run
    assert atm1(r, "monthly")["carry_pts_per_session"] > atm1(base, "monthly")["carry_pts_per_session"]


def test_the_pipeline_endpoint_adds_the_measured_spreads_only_when_they_exist(monkeypatch):
    import backtest.nifty_pipeline as npl
    import main
    monkeypatch.setattr(npl, "load_nifty_pipeline", lambda: {
        "computed_at": "x", "prereg_hash": "h", "tests_in_family": 5, "preregistered": {"hypotheses": {}},
        "hypotheses": []})
    cells = [{"expiry": e, "moneyness": "ATM", "hold": h, "carry_pts_per_session": float(h)}
             for e in ("nearest", "monthly") for h in (1, 3, 5)]
    choice = {"directional": {"expiry": "nearest", "moneyness": "ATM"}}
    inst = {"period": {}, "rule": "r", "cells": cells, "choices": choice,
            "without_assumed_slippage": {"cells": cells, "choices": choice}}
    monkeypatch.setattr(ins, "load_instrument_study", lambda: inst)
    out = main.nifty_pipeline()["instrument"]
    assert out["measured"] is None and all("carry_pts_measured" not in r for r in out["rows"])

    measured_cells = [{**c, "carry_pts_per_session": c["carry_pts_per_session"] + 10} for c in cells]
    inst["with_measured_spreads"] = {"sessions": ["2026-10-01"], "window": "14:30-15:30", "basis": "close",
                                     "cells": measured_cells, "caveat": "c",
                                     "choices": {"directional": {"expiry": "monthly", "moneyness": "ATM"},
                                                 "event_straddle": {"expiry": "monthly", "hold": 1}}}
    out = main.nifty_pipeline()["instrument"]
    assert out["measured"] == {"sessions": ["2026-10-01"], "window": "14:30-15:30", "basis": "close",
                               "chosen": {"expiry": "monthly", "moneyness": "ATM"}, "chosen_atm": "monthly",
                               "caveat": "c"}
    assert [r["carry_pts_measured"] for r in out["rows"]] == [11.0, 13.0, 15.0, 11.0, 13.0, 15.0]
