"""Machine and process checks at the spec's thresholds: a slow or hung API,
a memory leak (whose restart waits for the close), a slow render, a filling
disk, a drifting clock, a Mac set to sleep, and a restart after a power cut."""

from datetime import datetime

import pytest

from market_data.kite_session import IST
from sentinel import checks_machine as m
from sentinel import core

PMSET = """Battery Power:
 sleep                1
 disksleep            10
AC Power:
 womp                 1
 sleep                {ac}
 disksleep            0
"""


def test_a_slow_api_is_the_95th_percentile_over_ten_seconds():
    assert m.slow_api([0.1] * 5).ok
    assert not m.slow_api([0.1] * 4 + [11.0]).ok


def test_memory_over_one_and_a_half_gigabytes():
    assert m.memory({"api": 1536.0}).ok and not m.memory({"api": 1600.0, "web": 200.0}).ok
    ps = " 23872 /usr/bin/Python /x/api/.venv/bin/uvicorn main:app --port 8000\n 1700000 node server.mjs --port 3000\n 12 other\n"
    assert m.rss_by_service(ps) == {"api": pytest.approx(23872 / 1024), "web": pytest.approx(1700000 / 1024)}


def test_memory_restart_waits_for_the_close():
    ok, why = core.may_repair("restart_api_memory", datetime(2026, 10, 7, 11, 0, tzinfo=IST), {}, True, False,
                              allow_in_session=False)
    assert not ok and "market hours" in why


def test_a_slow_render_is_over_eight_seconds():
    assert m.slow_render(7.9).ok and not m.slow_render(8.1).ok


def test_the_disk_warns_under_five_and_is_critical_under_two_gigabytes():
    assert m.disk(5.0).ok
    assert m.disk(4.9).severity == "warn" and not m.disk(4.9).ok
    assert m.disk(1.9).severity == "critical"


def test_tidy_disk_never_touches_a_db(tmp_path):
    (tmp_path / "forward_log.db").write_bytes(b"x" * 100)
    big = tmp_path / "api_service.log"
    big.write_bytes(b"line\n" * 20)
    ok, msg = m.tidy_disk(tmp_path, limit_bytes=50)
    assert ok and (tmp_path / "forward_log.db").read_bytes() == b"x" * 100
    assert big.stat().st_size == 0 and (tmp_path / "api_service.log.1.gz").exists()


def test_the_clock_is_off_beyond_thirty_seconds():
    assert m.clock(29.0).ok and not m.clock(-31.0).ok


def test_a_mac_set_to_sleep_on_power_is_found_with_the_command():
    assert m.sleep_setting(PMSET.format(ac=0)).ok
    f = m.sleep_setting(PMSET.format(ac=1))
    assert not f.ok and "sudo pmset -c sleep 0" in f.summary


def test_a_restart_after_a_power_cut():
    assert m.power_cut(10.0, True).severity == "info" and not m.power_cut(10.0, True).ok
    assert m.power_cut(10.0, False).ok and m.power_cut(60.0, True).ok


def test_the_checks_are_registered_for_their_modes():
    keys = {c.key: c.modes for c in m.machine_checks()}
    assert keys["slow_api"] == ("fast",) and keys["sleep_setting"] == ("deep",) and keys["clock"] == ("deep",)
