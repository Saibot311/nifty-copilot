"""Which strike the paper book buys with the money it has (asked for on
2026-09-24): the best 2018-23 median trade among the strikes whose whole lot
fits — never the mean, which buys lottery tickets, and never the holdout."""

import sqlite3

import pytest

from briefing import option_choice as oc


def _conn(premiums):
    """One expiry, strikes around 23,000; `premiums` maps strike -> close."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, "
              "close REAL, open_interest REAL)")
    c.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?,?)",
                  [("2026-09-24", "2026-10-13", float(k), "CE", p, 5000.0) for k, p in premiums.items()])
    return c


# Strikes for spot 23,000, direction-aware as pattern_options: -2% ITM is 22,540 for a call.
PREMIUMS = {22550: 520.0, 22750: 380.0, 23000: 200.0, 23250: 110.0, 23450: 60.0}
MENU = [  # a menu shaped like the 2018-23 table: medians fall away from the money, means rise
    {"moneyness_pct": -2.0, "label": "2% ITM", "dev_trades": 246, "dev_median_pct": -1.0, "dev_mean_pct": 1.1},
    {"moneyness_pct": -1.0, "label": "1% ITM", "dev_trades": 246, "dev_median_pct": -7.3, "dev_mean_pct": 2.4},
    {"moneyness_pct": 0.0, "label": "ATM", "dev_trades": 246, "dev_median_pct": -22.6, "dev_mean_pct": 3.7},
    {"moneyness_pct": 1.0, "label": "1% OTM", "dev_trades": 246, "dev_median_pct": -39.7, "dev_mean_pct": 7.9},
    {"moneyness_pct": 2.0, "label": "2% OTM", "dev_trades": 246, "dev_median_pct": -63.8, "dev_mean_pct": 18.0},
]


def _choose(budget_lots):
    return oc.choose(_conn(PREMIUMS), MENU, option_type="CE", dte=7, entry_date="2026-09-24", spot=23000.0,
                     planned_exit=None, lots_for=budget_lots)


def _budget(rs):
    return lambda premium: int(rs // (premium * 65 * 1.033))


def test_with_enough_money_it_buys_the_deepest_in_the_money_strike():
    out = _choose(_budget(40_000))
    assert out["choice"]["label"] == "2% ITM" and out["choice"]["strike"] == 22550.0


def test_when_in_the_money_does_not_fit_it_steps_toward_the_money_only_as_far_as_it_must():
    out = _choose(_budget(20_000))           # 2% ITM ~Rs 34.9k and 1% ITM ~Rs 25.5k a lot do not fit
    assert out["choice"]["label"] == "ATM"
    assert [c["fits"] for c in out["compared"]] == [False, False, True, True, True]
    assert "did not fit" in out["summary"] and "2% ITM" in out["summary"]


def test_it_judges_by_the_median_trade_not_the_mean():
    """2% OTM calls averaged +18% on 2018-23 and the typical one lost 64%:
    the mean would buy the lottery ticket every time."""
    out = _choose(_budget(1_000_000))
    assert out["choice"]["label"] == "2% ITM"
    assert max(MENU, key=lambda c: c["dev_mean_pct"])["label"] == "2% OTM"


def test_nothing_fits_is_said_plainly():
    out = _choose(_budget(3_000))
    assert out["choice"] is None and "no strike" in out["summary"]


def test_the_menu_is_judged_on_2018_to_2023_only(monkeypatch, tmp_path):
    """Trades that finish in the holdout never reach the judgement."""
    monkeypatch.setattr(oc, "MENU_PATH", tmp_path / "menu.json")
    T = lambda r, exit_date: type("T", (), {"net_return_pct": r, "exit_date": exit_date, "entry_premium": 100.0})()
    monkeypatch.setattr(oc, "_trades", lambda option_type, m, dte, hold:
                        [T(-10.0, "2020-01-10")] * 40 + [T(90.0, "2024-02-01")] * 40)
    menu = oc.baseline_menu("CE", 7, 5)
    assert len(menu) == 5 and all(c["dev_median_pct"] == -10.0 and c["dev_trades"] == 40 for c in menu)
    assert oc.baseline_menu("CE", 7, 5) == menu  # cached: the development period does not change


def test_a_patterns_menu_keeps_its_tested_expiry_and_hold():
    row = {"suggested_option": {"moneyness_pct": -2.0, "min_days_to_expiry": 7, "hold_days": 5},
           "dev_grid": [{"m": m, "dte": dte, "hold": hold, "num_trades": 12, "median_return_pct": -m,
                         "avg_return_pct": 1.0} for m in (-2.0, 0.0, 2.0) for dte in (7, 14) for hold in (3, 5)]}
    menu = oc.pattern_menu(row)
    assert {c["moneyness_pct"] for c in menu} == {-2.0, 0.0, 2.0}
    assert len(menu) == 3  # only the tested expiry (7) and hold (5)
