"""The five-minute option snapshots: the only intraday option prices there
will ever be. What must hold: a chain is recorded only in the session and only
if NSE stamped it inside today's session; strikes near the money only; rows are
only ever added."""

import importlib.util
import inspect
from datetime import datetime
from pathlib import Path

import pytest

from market_data.kite_session import IST
from storage import option_snapshots_db as db

spec = importlib.util.spec_from_file_location("snapshot_options", Path(__file__).parent.parent / "scripts" / "snapshot_options.py")
snap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snap)

EXPIRIES = ["06-Oct-2026", "13-Oct-2026", "19-Oct-2026", "27-Oct-2026", "24-Nov-2026"]
AT_10 = datetime(2026, 10, 1, 10, 5, tzinfo=IST)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "option_snapshots.db")


def _side(price):
    return {"identifier": "X", "lastPrice": price, "buyPrice1": price - 0.5, "sellPrice1": price + 0.5,
            "buyQuantity1": 650, "sellQuantity1": 325, "impliedVolatility": 12.5, "openInterest": 1000,
            "changeinOpenInterest": 10, "totalTradedVolume": 5000, "change": 1.0}


class FakeNSE:
    def __init__(self, stamp="01-Oct-2026 10:05:00", spot=22600.0):
        self.stamp, self.spot, self.asked = stamp, spot, []

    def option_chain_contract_info(self, symbol):
        return {"expiryDates": EXPIRIES}

    def index_option_chain(self, symbol, expiry):
        self.asked.append(expiry)
        strikes = range(20000, 25050, 50)
        return {"records": {"underlyingValue": self.spot, "timestamp": self.stamp,
                            "data": [{"strikePrice": k, "CE": _side(100.0), "PE": _side(90.0)} for k in strikes]}}


def test_it_runs_only_in_the_session_on_weekdays():
    assert snap.in_session(AT_10)
    assert not snap.in_session(datetime(2026, 10, 1, 9, 10, tzinfo=IST))
    assert not snap.in_session(datetime(2026, 10, 1, 15, 40, tzinfo=IST))
    assert not snap.in_session(datetime(2026, 10, 3, 11, 0, tzinfo=IST))      # a Saturday


def test_it_takes_the_two_nearest_expiries_and_the_nearest_monthly():
    assert snap.pick_expiries(EXPIRIES) == ["06-Oct-2026", "13-Oct-2026", "27-Oct-2026"]


def test_it_saves_strikes_within_five_percent_for_each_chosen_expiry():
    nse = FakeNSE()
    assert snap.main(AT_10, nse) == 0
    assert nse.asked == ["06-Oct-2026", "13-Oct-2026", "27-Oct-2026"]
    with db.connect() as conn:
        strikes = [r[0] for r in conn.execute("SELECT DISTINCT strike FROM snapshots ORDER BY strike")]
        row = conn.execute("SELECT * FROM snapshots WHERE strike = 22600 AND option_type = 'PE' "
                           "AND expiry = '2026-10-06'").fetchone()
    assert min(strikes) >= 22600 * 0.95 and max(strikes) <= 22600 * 1.05
    assert row["taken_at"] == "2026-10-01T10:05:00" and row["bid"] == 89.5 and row["ask"] == 90.5
    assert row["bid_qty"] == 650 and row["iv"] == 12.5 and row["spot"] == 22600.0


def test_the_same_snapshot_twice_is_one_row_and_the_first_is_kept():
    snap.main(AT_10, FakeNSE())
    n = db.summary()["n"]
    changed = FakeNSE()
    changed.index_option_chain = lambda s, e: {"records": {"underlyingValue": 22600.0, "timestamp": "01-Oct-2026 10:05:00",
                                                          "data": [{"strikePrice": 22600, "CE": _side(1.0), "PE": _side(1.0)}]}}
    snap.main(AT_10, changed)
    assert db.summary()["n"] == n
    with db.connect() as conn:
        assert conn.execute("SELECT ltp FROM snapshots WHERE strike = 22600 AND option_type = 'CE' "
                            "AND expiry = '2026-10-06'").fetchone()[0] == 100.0


def test_a_chain_stamped_outside_todays_session_is_not_recorded():
    """After the close NSE restamps the last chain (15:40 on 30 Sep 2026)."""
    snap.main(datetime(2026, 10, 1, 15, 34, tzinfo=IST), FakeNSE(stamp="01-Oct-2026 15:40:00"))
    snap.main(AT_10, FakeNSE(stamp="30-Sep-2026 15:30:00"))            # a holiday: yesterday's chain
    assert db.summary()["n"] == 0
    with db.connect() as conn:
        assert [r[0] for r in conn.execute("SELECT outcome FROM runs")] == ["closed", "closed"]


def test_outside_the_session_nothing_is_asked():
    nse = FakeNSE()
    assert snap.main(datetime(2026, 10, 1, 20, 0, tzinfo=IST), nse) == 0 and nse.asked == []


def test_a_failed_fetch_is_logged_and_retried_next_run():
    class Down(FakeNSE):
        def option_chain_contract_info(self, symbol):
            raise ConnectionError("NSE unreachable")
    assert snap.main(AT_10, Down()) == 1
    with db.connect() as conn:
        assert conn.execute("SELECT outcome FROM runs").fetchone()[0] == "failed"


def test_the_store_only_ever_adds_rows():
    source = inspect.getsource(db).upper()
    assert "UPDATE " not in source and "DELETE " not in source and "INSERT OR REPLACE" not in source


def test_the_nightly_backup_keeps_a_week_of_copies(tmp_path):
    from storage.backup import SNAPSHOTS_KEEP, backup_option_snapshots
    snap.main(AT_10, FakeNSE())
    r = backup_option_snapshots(dest_dir=tmp_path / "backups")
    assert r["ok"] and r["rows"] == db.summary()["n"] and SNAPSHOTS_KEEP == 7
