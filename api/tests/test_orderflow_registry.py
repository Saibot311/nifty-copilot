"""The four registered order-flow rules: an edited registration, a rule that
decides at the wrong snapshot, or a verdict logged twice are the ways this
could mislead."""

import hashlib
import json

import backtest.orderflow_registry as reg


def test_the_registration_has_not_been_edited():
    # Registered 2026-10-01 after the session, before any rule was run on any session.
    fixed = json.dumps({**reg.PREREGISTERED, "tests": reg.TESTS_IN_FAMILY, "registered_on": reg.REGISTERED_ON.isoformat(),
                        "entry_delay_s": reg.ENTRY_DELAY_S, "max_late_s": reg.MAX_LATE_S}, sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH == reg.PREREG_HASH


PREREGISTERED_HASH = "57c29550776a8810"  # a literal: computing it live would pass any edit


def snap(at, **f):
    base = {"taken_at": f"2026-10-05T{at}:00", "open_ok": True, "oi_flow_open": None, "vol_spread_chg_open": None,
            "near_call_imbalance": None, "near_put_imbalance": None, "days_to_expiry": 1, "max_oi_dist_pct": None}
    return {**base, **f}


def test_a_and_b_decide_once_at_the_first_snapshot_from_11_00():
    hist = [snap("10:55", oi_flow_open=0.02), snap("11:00", oi_flow_open=0.02, vol_spread_chg_open=-0.4)]
    assert reg.oi_flow_decide(hist[:1], None) is None                         # before 11:00
    assert reg.oi_flow_decide(hist, None) == 1 and reg.vol_spread_decide(hist, None) == -1
    later = hist + [snap("11:05", oi_flow_open=0.02)]
    assert reg.oi_flow_decide(later, None) is None                            # not the first at or after 11:00
    assert reg.oi_flow_decide([snap("10:55"), snap("11:00", oi_flow_open=0.02, open_ok=False)], None) is None


def test_c_needs_five_snapshots_of_book_in_the_last_half_hour():
    hist = [snap(f"10:{m:02d}", near_call_imbalance=0.3, near_put_imbalance=0.1) for m in (35, 40, 45, 50, 55)]
    assert reg.book_decide(hist + [snap("11:00", near_call_imbalance=0.3, near_put_imbalance=0.1)], None) == 1
    assert reg.book_decide(hist[-3:] + [snap("11:00", near_call_imbalance=0.3, near_put_imbalance=0.1)], None) is None


def test_d_trades_only_on_expiry_day_toward_the_largest_oi_strike():
    assert reg.pin_decide([snap("12:55"), snap("13:00", days_to_expiry=0, max_oi_dist_pct=0.4)], None) == -1
    assert reg.pin_decide([snap("12:55"), snap("13:00", days_to_expiry=0, max_oi_dist_pct=-0.3)], None) == 1
    assert reg.pin_decide([snap("12:55"), snap("13:00", days_to_expiry=0, max_oi_dist_pct=0.1)], None) is None
    assert reg.pin_decide([snap("12:55"), snap("13:00", days_to_expiry=1, max_oi_dist_pct=0.4)], None) is None


def test_every_rule_is_judged_at_69_from_2_october_with_its_own_minimums():
    for name in reg.RULES:
        s = reg.spec(name)
        h = reg.PREREGISTERED["hypotheses"][name]
        assert (s.tests_in_family, s.registered_on.isoformat(), s.min_sessions, s.min_trades) == \
            (69, "2026-10-02", h["min_sessions"], h["min_trades"])


def test_before_the_minimums_each_rule_waits_and_nothing_is_logged(tmp_path, monkeypatch):
    import backtest.hypothesis_log as hl
    logged = []
    monkeypatch.setattr(hl, "log_run", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(reg, "evaluate", lambda rule, spec, db_path=None: {
        "rule": rule.name, "trades": [], "status": "waiting", "sessions": 3, "counted_trades": 2,
        "min_sessions": spec.min_sessions, "min_trades": spec.min_trades, "reason": "Not judged"})
    out = reg.run_orderflow_forward(result_path=tmp_path / "of.json")
    assert [h["status"] for h in out["hypotheses"]] == ["waiting"] * 4 and logged == []
    assert reg.load_orderflow_forward(tmp_path / "of.json")["prereg_hash"] == reg.PREREG_HASH


def test_a_judged_rule_is_logged_once_however_often_it_is_rerun(tmp_path, monkeypatch):
    import backtest.hypothesis_log as hl
    logged = []
    monkeypatch.setattr(hl, "log_run", lambda name, *a, **k: logged.append(name))
    monkeypatch.setattr(reg, "evaluate", lambda rule, spec, db_path=None: {
        "rule": rule.name, "trades": [], "status": "judged" if rule.name == "book_pressure_30m" else "waiting",
        "num_trades": 250, "mean_pct": -1.0})
    for _ in range(3):
        reg.run_orderflow_forward(result_path=tmp_path / "of.json")
    assert logged == ["orderflow_book_pressure_30m"]
