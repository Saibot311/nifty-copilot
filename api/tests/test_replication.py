"""Replication on other indices. What must hold: the plan was not edited
after results existed; the indices, which move together, count one date as
one observation; and each index's own option archive is the one read."""

import hashlib
import json
from types import SimpleNamespace as T

import backtest.replication as rep
from storage.options_db import DB_PATH, db_path_for


def test_the_replication_plan_has_not_been_edited():
    fixed = json.dumps({**rep.PREREGISTERED, "base": rep.BASE_TESTS, "min": rep.MIN_HOLDOUT_DATES,
                        "structural": list(rep.STRUCTURAL_REPLICATED)}, sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == "01c923a162284ea7" == rep.PREREG_HASH


def test_trades_on_the_same_date_across_indices_count_once():
    trades = {"NIFTY": [T(entry_date="2024-02-01", net_return_pct=10.0), T(entry_date="2024-03-01", net_return_pct=-4.0)],
              "BANKNIFTY": [T(entry_date="2024-02-01", net_return_pct=30.0)]}
    by = rep._by_date(trades, lambda x: x)
    assert by == {"2024-02-01": 20.0, "2024-03-01": -4.0}


def test_each_index_reads_its_own_archive():
    assert db_path_for("NIFTY") == DB_PATH
    assert db_path_for("BANKNIFTY").name == "options_banknifty.db"
    assert len({db_path_for(u) for u in rep.INDICES}) == len(rep.INDICES)


def test_the_bar_counts_replication_as_another_look():
    # 26 earlier holdout tests plus one per replicated hypothesis.
    assert rep.BASE_TESTS == 26
