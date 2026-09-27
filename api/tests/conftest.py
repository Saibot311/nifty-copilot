"""Setup every test gets."""

import pytest

import backtest.hypothesis_log as hl


@pytest.fixture(autouse=True)
def hypothesis_log_in_tmp(tmp_path, monkeypatch):
    """The hypothesis log is the append-only record of every strategy and
    parameter set ever tested, and it cannot be rebuilt. Anything a test
    runs that logs a hypothesis (judge() in replication, the research
    runners) would otherwise append to the real file and add a phantom to
    the distinct count. Each test gets its own empty log instead."""
    monkeypatch.setattr(hl, "LOG_PATH", tmp_path / "hypothesis_log.jsonl")
