"""The live option-chain trade: scan until one locks, track it to one exit (options/chain_trade_live.py)."""

import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from market_data.kite_session import IST
from options import chain_trade_live as live
from storage import chain_trade_db as db
from tests.test_chain_trade import table

TODAY = "2026-10-12"          # a Monday


def at(h, m):
    return datetime(2026, 10, 12, h, m, tzinfo=IST)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "chain_trade.db"


def chain(put_add=1000, call_add=0, **kw):
    t = table(put_add=put_add, call_add=call_add, **kw)
    t["as_of"] = "12-Oct-2026 10:30:00"
    return t


def with_mark(t, strike, side, bid, ltp=None, spot=None):
    for r in t["rows"]:
        if r["strike"] == strike:
            r["call" if side == "CE" else "put"].update({"bid": bid, "ltp": ltp})
    if spot is not None:
        t["underlying_value"] = spot
    return t


def lock_ce(path, now=None):
    out = live.scan_and_track(now or at(10, 35), chain(), path)
    assert out["did"] == "locked"
    return db.suggestion_for(TODAY, path)["trade"]


def test_scan_locks_only_the_first_trade(path):
    live.scan_and_track(at(10, 0), chain(put_add=0), path)             # no trade
    assert db.suggestion_for(TODAY, path) is None
    assert db.last_scan(TODAY, path)["action"] == "NO_TRADE" and db.last_scan(TODAY, path)["reason"]
    first = live.scan_and_track(at(10, 5), chain(), path)
    assert first["did"] == "locked"
    assert db.suggestion_for(TODAY, path)["trade"]["side"] == "CE"
    second = live.scan_and_track(at(10, 10), chain(put_add=0, call_add=1000), path)   # would be a put
    assert second["did"] == "track"
    assert db.suggestion_for(TODAY, path)["trade"]["side"] == "CE"
    assert db.suggestion_for(TODAY, path)["trade"]["sizing"] is None


def test_no_new_locks_outside_0920_to_1430(path):
    assert live.scan_and_track(at(9, 15), chain(), path)["did"] == "idle"
    assert live.scan_and_track(at(14, 35), chain(), path)["did"] == "idle"
    assert live.scan_and_track(datetime(2026, 10, 10, 11, 0, tzinfo=IST), chain(), path)["did"] == "idle"   # Saturday
    assert db.suggestion_for(TODAY, path) is None
    assert live.scan_and_track(at(14, 30), chain(), path)["did"] == "locked"


def test_a_chain_stamped_on_another_day_is_not_scanned(path):
    t = chain()
    t["as_of"] = "09-Oct-2026 15:40:00"
    assert live.scan_and_track(at(10, 0), t, path)["did"] == "scan"
    assert db.suggestion_for(TODAY, path) is None


def test_exit_on_target_with_pnl(path):
    tr = lock_ce(path)                                   # entry 100, target 140, stop 75, lot 65, charges 60
    out = live.scan_and_track(at(11, 20), with_mark(chain(), 25000.0, "CE", 141.0), path)
    assert out["did"] == "exit" and out["kind"] == "target"
    ex = db.exit_for(TODAY, path)
    assert ex["premium"] == 141.0 and ex["premium_source"] == "bid"
    assert ex["pnl_per_unit"] == 41.0
    assert ex["pnl_per_lot"] == pytest.approx(41.0 * 65 - tr["charges_rs"])


def test_exit_on_stop_and_stop_wins_over_target_in_one_check(path):
    lock_ce(path)
    tr = db.suggestion_for(TODAY, path)["trade"]
    tr["stop"], tr["target"] = 120.0, 110.0               # both true at 115: the cautious reading is the stop
    assert live.exit_kind(tr, at(11, 0), 115.0, 25000.0) == "stop"
    assert live.scan_and_track(at(11, 0), with_mark(chain(), 25000.0, "CE", 74.0), path)["kind"] == "stop"
    assert db.exit_for(TODAY, path)["pnl_per_unit"] == -26.0


def test_invalidation_for_a_call_is_below_and_for_a_put_above():
    ce = {"side": "CE", "stop": 75.0, "target": 140.0, "expiry": "20-Oct-2026", "levels": {"invalidation_index": 24900}}
    pe = {**ce, "side": "PE"}
    assert live.exit_kind(ce, at(11, 0), 100.0, 24890.0) == "invalidated"
    assert live.exit_kind(ce, at(11, 0), 100.0, 24950.0) is None
    assert live.exit_kind(pe, at(11, 0), 100.0, 24950.0) == "invalidated"
    assert live.exit_kind(pe, at(11, 0), 100.0, 24890.0) is None
    ce["levels"]["invalidation_index"] = None
    assert live.exit_kind(ce, at(11, 0), 100.0, 1.0) is None


def test_precedence_stop_target_invalidated_time():
    tr = {"side": "CE", "stop": 75.0, "target": 140.0, "expiry": "20-Oct-2026", "levels": {"invalidation_index": 24900}}
    assert live.exit_kind(tr, at(15, 20), 100.0, 24000.0) == "invalidated"      # over time
    assert live.exit_kind(tr, at(15, 20), 150.0, 24000.0) == "target"           # over invalidation
    assert live.exit_kind(tr, at(15, 20), 70.0, 24000.0) == "stop"


def test_time_exit_at_1515_or_1430_on_expiry_day():
    tr = {"side": "CE", "stop": 75.0, "target": 140.0, "expiry": "20-Oct-2026", "levels": {"invalidation_index": None}}
    assert live.exit_kind(tr, at(15, 10), 100.0, 25000.0) is None
    assert live.exit_kind(tr, at(15, 15), 100.0, 25000.0) == "time"
    tr["expiry"] = "12-Oct-2026"
    assert live.exit_kind(tr, at(14, 25), 100.0, 25000.0) is None
    assert live.exit_kind(tr, at(14, 30), 100.0, 25000.0) == "time"


def test_exactly_one_exit_even_if_checked_again(path):
    lock_ce(path)
    live.scan_and_track(at(15, 15), with_mark(chain(), 25000.0, "CE", 90.0), path)
    assert db.exit_for(TODAY, path)["kind"] == "time"
    again = live.scan_and_track(at(15, 20), with_mark(chain(), 25000.0, "CE", 150.0), path)
    assert again["did"] == "idle"
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT COUNT(*) FROM exits").fetchone()[0] == 1
    assert db.exit_for(TODAY, path)["kind"] == "time"


def test_last_price_stands_in_for_a_missing_bid_and_says_so(path):
    lock_ce(path)
    live.scan_and_track(at(11, 0), with_mark(chain(), 25000.0, "CE", None, ltp=145.0), path)
    ex = db.exit_for(TODAY, path)
    assert ex["kind"] == "target" and ex["premium_source"] == "last"


def test_tables_refuse_update_and_delete(path):
    lock_ce(path)
    live.scan_and_track(at(15, 15), chain(), path)
    for name in ("suggestions", "exits", "scans"):
        with sqlite3.connect(path) as c:
            with pytest.raises(sqlite3.DatabaseError):
                c.execute(f"UPDATE {name} SET session = 'x'")
            with pytest.raises(sqlite3.DatabaseError):
                c.execute(f"DELETE FROM {name}")


def test_live_block_phases(path):
    assert live.live_block(at(8, 0), None, None, 2.0, path)["phase"] == "not_trading"
    live.scan_and_track(at(10, 0), chain(put_add=0), path)
    b = live.live_block(at(10, 0), None, None, 2.0, path)
    assert b["phase"] == "scanning" and b["last_scan"]["reason"]
    lock_ce(path)
    t = with_mark(chain(), 25000.0, "CE", 107.5)
    b = live.live_block(at(11, 0), t, 100000.0, 2.0, path)
    assert b["phase"] == "locked" and b["mark"]["premium"] == 107.5
    assert b["pnl_per_unit"] == 7.5 and b["position"] == pytest.approx((107.5 - 75) / 65, abs=0.001)
    assert b["sizing"]["lots"] >= 1 and b["pnl_for_plan"] == b["sizing"]["lots"] * b["pnl_per_lot"]
    live.scan_and_track(at(15, 15), t, path)
    b = live.live_block(at(15, 16), t, None, 2.0, path)
    assert b["phase"] == "closed" and b["exit"]["kind"] == "time"


def test_a_failing_chain_trade_never_costs_the_snapshot(capsys):
    spec = importlib.util.spec_from_file_location(
        "snapshot_options_fresh", Path(__file__).parent.parent / "scripts" / "snapshot_options.py")
    snap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(snap)

    class Boom:
        def index_option_chain(self, *a):
            raise RuntimeError("NSE down")

    snap.record_chain_trade(at(10, 5), Boom(), ["20-Oct-2026"])         # prints, never raises
    assert "chain trade FAILED" in capsys.readouterr().out
