"""Order-flow features on made-up snapshot rows: each feature checked against
numbers worked by hand, and none of them able to see a snapshot taken after
its own."""

import random
from datetime import date, datetime

import pytest

import backtest.orderflow_features as of
from storage import option_snapshots_db

DAY = date(2026, 10, 1)
EXPIRY = "2026-10-06"
STRIKES = tuple(range(22300, 22751, 50))


def chain(clock: str, spot: float, expiry: str = EXPIRY, day: date = DAY, strikes=STRIKES, over=None) -> list[dict]:
    """One expiry's chain at `clock` on `day`: calls worth 100 + half of
    (spot - strike), puts the mirror, a 0.5 spread, 650 a side on the book,
    IV 12, OI 1,000 — then `over` = {(strike, "CE"|"PE"): {field: value}}."""
    rows = []
    for k in strikes:
        for kind in ("CE", "PE"):
            mid = 100 + 0.5 * ((spot - k) if kind == "CE" else (k - spot))
            r = {"taken_at": f"{day.isoformat()}T{clock}", "expiry": expiry, "strike": float(k), "option_type": kind,
                 "spot": spot, "ltp": round(mid, 2), "bid": round(mid - 0.25, 2), "ask": round(mid + 0.25, 2),
                 "bid_qty": 650, "ask_qty": 650, "iv": 12.0, "oi": 1000, "volume": 0}
            r.update((over or {}).get((k, kind), {}))
            rows.append(r)
    return rows


def feats(*chains) -> list[dict]:
    rows = [r for c in chains for r in c]
    return of.session_features(of.snapshots(rows, EXPIRY))


def test_open_interest_change_since_the_open_and_the_put_call_ratio():
    # near the money at 22,500 +/- 2%: every strike 22,300-22,750 is in (22,050-22,950)
    first = chain("09:19:00", 22500)
    later = chain("10:00:00", 22500, over={(22500, "CE"): {"oi": 1400}, (22450, "PE"): {"oi": 2000},
                                           (22600, "PE"): {"oi": 1200}})
    f = feats(first, later)[-1]
    n = len(STRIKES)
    assert f["call_oi_near"] == 1000 * n + 400 and f["put_oi_near"] == 1000 * n + 1200
    assert f["call_oi_chg_open"] == 400 and f["put_oi_chg_open"] == 1200
    assert f["pcr_oi"] == round((1000 * n + 1200) / (1000 * n + 400), 4)
    assert f["pcr_oi_chg_open"] == round((1000 * n + 1200) / (1000 * n + 400) - 1, 4)
    assert f["oi_flow_open"] == round((1200 - 400) / (2000 * n), 6)


def test_the_thirty_minute_change_needs_a_snapshot_thirty_to_forty_minutes_back():
    s0 = chain("09:20:00", 22500)
    s1 = chain("09:50:00", 22500, over={(22500, "CE"): {"oi": 1100}})
    s2 = chain("10:20:00", 22500, over={(22500, "CE"): {"oi": 1500}, (22500, "PE"): {"oi": 900}})
    f = feats(s0, s1, s2)
    assert f[1]["ref_30m_at"] == "2026-10-01T09:20:00" and f[1]["call_oi_chg_30m"] == 100
    assert f[2]["ref_30m_at"] == "2026-10-01T09:50:00"
    assert (f[2]["call_oi_chg_30m"], f[2]["put_oi_chg_30m"]) == (400, -100)
    # a recorder gap: the only earlier snapshot is 61 minutes back, too old to be "30 minutes ago"
    g = feats(s0, chain("10:21:00", 22500))[-1]
    assert g["ref_30m_at"] is None and g["call_oi_chg_30m"] is None


def test_a_session_whose_first_snapshot_is_late_has_no_open():
    f = feats(chain("10:00:00", 22500), chain("10:30:00", 22600))[-1]
    assert f["open_ok"] is False
    for k in ("spot_chg_open_pct", "call_oi_chg_open", "put_oi_chg_open", "pcr_oi_chg_open", "oi_flow_open",
              "atm_iv_chg_open", "vol_spread_chg_open", "skew_1pct_chg_open", "max_call_build_strike"):
        assert f[k] is None, k
    assert f["pcr_oi"] == 1.0 and f["atm_strike"] == 22600       # features of the moment are still there


def test_book_imbalance_at_the_money_and_around_it():
    over = {(22500, "CE"): {"bid_qty": 900, "ask_qty": 100}, (22450, "CE"): {"bid_qty": 0, "ask_qty": 1000},
            (22500, "PE"): {"bid_qty": 0, "ask_qty": 0}}
    f = feats(chain("09:20:00", 22510, over=over))[-1]
    assert f["atm_strike"] == 22500
    assert f["atm_call_imbalance"] == 0.8
    # 22,400-22,600: bids 900 + 0 + 3 x 650, asks 100 + 1000 + 3 x 650
    assert f["near_call_imbalance"] == round((2850 - 3050) / (2850 + 3050), 4)
    assert f["atm_put_imbalance"] is None                         # an empty book is not "balanced"


def test_atm_iv_vol_spread_and_skew():
    over = {(22500, "CE"): {"iv": 13.0}, (22500, "PE"): {"iv": 11.0}, (22550, "CE"): {"iv": 12.5},
            (22450, "PE"): {"iv": 0}, (22050, "PE"): {"iv": 15.0}}
    s0 = chain("09:20:00", 22500, strikes=tuple(range(22000, 23001, 50)))
    s1 = chain("10:00:00", 22510, strikes=tuple(range(22000, 23001, 50)), over=over)
    f0, f1 = of.session_features(of.snapshots(s0 + s1, EXPIRY))
    assert (f1["atm_call_iv"], f1["atm_put_iv"], f1["atm_iv"]) == (13.0, 11.0, 12.0)
    assert f1["atm_iv_chg_open"] == 0.0
    # three strikes nearest 22,510: 22,500 (+2), 22,550 (+0.5), 22,450 (put IV missing: left out)
    assert f1["vol_spread"] == 1.25 and f1["vol_spread_chg_open"] == 1.25
    # 1%: put nearest 22,284.9 is 22,300 (12), call nearest 22,735.1 is 22,750 (12)
    assert f1["skew_1pct"] == 0.0
    # 2%: put nearest 22,059.8 is 22,050 (15), call nearest 22,960.2 is 22,950 (12)
    assert f1["skew_2pct"] == 3.0 and f1["skew_2pct_chg_open"] == 3.0
    assert f0["skew_2pct"] == 0.0


def test_the_largest_build_up_and_the_largest_open_interest():
    s0 = chain("09:20:00", 22500)
    s1 = chain("11:00:00", 22520, over={(22700, "CE"): {"oi": 9000}, (22600, "CE"): {"oi": 3000},
                                        (22350, "PE"): {"oi": 4000}, (22400, "PE"): {"oi": 400}})
    f = feats(s0, s1)[-1]
    assert (f["max_call_build_strike"], f["max_call_build_oi"], f["max_call_build_dist_pts"]) == (22700, 8000, 180)
    assert (f["max_put_build_strike"], f["max_put_build_oi"], f["max_put_build_dist_pts"]) == (22350, 3000, -170)
    assert f["max_oi_strike"] == 22700
    assert f["max_oi_dist_pct"] == round((22520 - 22700) / 22520 * 100, 4)
    assert feats(s0, chain("11:00:00", 22500))[-1]["max_call_build_strike"] is None   # nothing rose


def test_the_spread_in_points_and_a_bad_quote():
    over = {(22500, "CE"): {"bid": 0, "ask": 101}, (22500, "PE"): {"bid": 102.0, "ask": 101.0}}
    f = feats(chain("09:20:00", 22500))[-1]
    assert f["atm_call_spread"] == 0.5 and f["atm_call_spread_pct"] == 0.5
    g = feats(chain("09:20:00", 22500, over=over))[-1]
    assert g["atm_call_spread"] is None and g["atm_put_spread"] is None      # no bid; a crossed quote


def test_expiries_are_never_mixed():
    rows = chain("09:20:00", 22500) + chain("09:20:30", 22501, expiry="2026-10-13",
                                            over={(22500, "CE"): {"oi": 99999}})
    snaps = of.snapshots(rows, EXPIRY)
    assert len(snaps) == 1 and snaps[0]["spot"] == 22500
    assert of.features_at(snaps)["call_oi_near"] == 1000 * len(STRIKES)


def test_the_traded_expiry_is_the_nearest_not_expiring_that_day():
    exp = [date(2026, 10, 6), date(2026, 10, 13), date(2026, 10, 27)]
    assert of.traded_expiry(date(2026, 10, 1), exp) == date(2026, 10, 6)
    assert of.traded_expiry(date(2026, 10, 6), exp) == date(2026, 10, 13)
    assert of.traded_expiry(date(2026, 10, 27), exp) is None


def random_session(seed: int, n: int = 40) -> list[dict]:
    rng = random.Random(seed)
    rows, spot = [], 22500.0
    for i in range(n):
        spot += rng.gauss(0, 15)
        minute = 9 * 60 + 19 + 5 * i + rng.randint(0, 1)
        over = {(k, kind): {"oi": rng.randint(500, 5000), "iv": round(rng.uniform(9, 16), 2),
                            "bid_qty": rng.choice([0, 65, 130, 650]), "ask_qty": rng.choice([0, 65, 260]),
                            "bid": round(rng.uniform(50, 150), 2), "ask": round(rng.uniform(50, 151), 2)}
                for k in STRIKES for kind in ("CE", "PE")}
        rows += chain(f"{minute // 60:02d}:{minute % 60:02d}:{rng.randint(0, 59):02d}", round(spot, 2), over=over)
    return rows


def scrambled_after(rows: list[dict], t: str, seed: int) -> list[dict]:
    """Every row stamped after t replaced with nonsense, and one more snapshot added."""
    rng = random.Random(seed)
    out = []
    for r in rows:
        if r["taken_at"] <= t:
            out.append(r)
            continue
        out.append({**r, "spot": rng.uniform(20000, 25000), "oi": rng.randint(0, 10**6), "iv": rng.uniform(1, 90),
                    "bid": rng.uniform(1, 500), "ask": rng.uniform(1, 500), "bid_qty": rng.randint(0, 9999),
                    "ask_qty": rng.randint(0, 9999)})
    return out + chain("15:29:00", 23000, over={(22500, "CE"): {"oi": 10**7}})


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_feature_at_t_changes_when_every_later_snapshot_is_scrambled(seed):
    rows = random_session(seed)
    full = of.session_features(of.snapshots(rows, EXPIRY))
    assert len(full) == 40 and any(f["call_oi_chg_30m"] is not None for f in full)
    for k in range(0, len(full), 3):
        t = full[k]["taken_at"]
        again = of.session_features(of.snapshots(scrambled_after(rows, t, seed + k), EXPIRY))
        assert again[k] == full[k], t


def test_rows_are_read_back_from_the_database_without_writing_to_it(tmp_path):
    path = tmp_path / "snapshots.db"
    option_snapshots_db.save(chain("09:20:00", 22500) + chain("09:20:00", 22500, day=date(2026, 10, 5)), path)
    rows = of.read_rows(path, start=DAY, end=DAY)
    assert len(rows) == 2 * len(STRIKES) and {r["taken_at"][:10] for r in rows} == {"2026-10-01"}
    assert set(of.by_session(of.read_rows(path))) == {DAY, date(2026, 10, 5)}
    missing = tmp_path / "none.db"
    assert of.read_rows(missing) == [] and not missing.exists()


def test_a_snapshot_time_is_nse_s_own_stamp():
    snaps = of.snapshots(chain("09:20:07", 22500), EXPIRY)
    assert snaps[0]["taken_at"] == datetime(2026, 10, 1, 9, 20, 7)
    f = of.features_at(snaps)
    assert (f["expiry"], f["days_to_expiry"]) == (EXPIRY, 5)
