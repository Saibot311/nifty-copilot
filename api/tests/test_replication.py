"""Replication on other indices. What must hold: the plan was not edited
after results existed; the indices, which move together, count one date as
one observation; and each index's own option archive is the one read."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as T

import backtest.hypothesis_log as hl
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


def test_the_edge_over_no_signal_is_computed_here_not_in_the_browser():
    """The dashboard showed each index's edge by subtracting two returned
    numbers in the client — a statistic made in JavaScript (I2). The API
    returns it now, and the pooled sort key with it."""
    import inspect
    source = inspect.getsource(rep.judge)
    assert '"holdout_edge_pct"' in source
    out = rep.judge("t", "T", {"NIFTY": [T(entry_date="2024-02-01", exit_date="2024-02-08", net_return_pct=30.0),
                                         T(entry_date="2024-03-01", exit_date="2024-03-08", net_return_pct=10.0)]},
                    {"NIFTY": [T(entry_date="2024-02-01", exit_date="2024-02-08", net_return_pct=-5.0),
                               T(entry_date="2024-03-01", exit_date="2024-03-08", net_return_pct=5.0)]}, tests=26)
    assert out["per_index"]["NIFTY"]["holdout_edge_pct"] == 20.0     # 20 mean vs 0 mean
    assert out["pooled"]["holdout_edge_pct"] == 20.0
    assert out["indices_beating_baseline_in_holdout"] == 1


def test_judging_in_a_test_never_reaches_the_real_hypothesis_log():
    """judge() logs what it judged to the hypothesis log, the append-only
    record of everything ever tested. Called from a test, that row went into
    the real file: 35 rows of a hypothesis named "t", one per pytest run. The
    check counts this test's own rows, not the file's bytes, because the API
    server may append real rows while the suite runs."""
    real = Path(hl.__file__).parent / "hypothesis_log.jsonl"

    def rows_named_t(path):
        if not path.exists():
            return 0
        with open(path) as f:
            return sum(json.loads(line).get("strategy") == "replication_t" for line in f if line.strip())

    before = rows_named_t(real)
    rep.judge("t", "T", {"NIFTY": [T(entry_date="2024-02-01", exit_date="2024-02-08", net_return_pct=30.0),
                                   T(entry_date="2024-03-01", exit_date="2024-03-08", net_return_pct=10.0)]},
              {"NIFTY": [T(entry_date="2024-02-01", exit_date="2024-02-08", net_return_pct=-5.0),
                         T(entry_date="2024-03-01", exit_date="2024-03-08", net_return_pct=5.0)]}, tests=26)
    assert rows_named_t(real) == before
    assert rows_named_t(hl.LOG_PATH) == 1  # logged all the same, to this test's own file
