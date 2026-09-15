"""Locks down the expectancy/profit-factor/drawdown formulas, and the two
real bugs found by hand this session: the hypothesis-log race condition
and the options drawdown that assumed unrealistic full reinvestment.
"""

import json
import threading

import pytest

from backtest.engine import Trade
from backtest.hypothesis_log import log_run, total_hypotheses_tested
from backtest.metrics import compute_metrics
from backtest.options_engine import OptionTrade
from backtest.options_research import REALISTIC_POSITION_FRACTION, _realistic_max_drawdown_pct


def _trade(net_return_pct, holding_days=10):
    return Trade(
        entry_date="2020-01-01", exit_date="2020-01-15", direction="long",
        entry_price=100.0, exit_price=100.0 * (1 + net_return_pct / 100),
        regime_at_entry="TREND_BULL", holding_days=holding_days,
        gross_return_pct=net_return_pct, cost_pct=0.0, net_return_pct=net_return_pct,
    )


def test_expectancy_matches_documented_formula():
    """EXPECTANCY = win_rate * avg_win - loss_rate * avg_loss, per the
    project spec's own stated formula."""
    trades = [_trade(10), _trade(10), _trade(-5), _trade(-5)]  # 50% win rate
    m = compute_metrics(trades)
    win_rate, avg_win, avg_loss = 0.5, 10.0, -5.0
    expected = win_rate * avg_win + (1 - win_rate) * avg_loss
    assert m["expectancy_pct"] == pytest.approx(expected, abs=1e-6)


def test_profit_factor_is_gross_win_over_gross_loss():
    trades = [_trade(20), _trade(-10), _trade(-10)]
    m = compute_metrics(trades)
    assert m["profit_factor"] == pytest.approx(20 / 20, abs=1e-6)


def test_all_winning_trades_gives_infinite_profit_factor_reported_as_none():
    trades = [_trade(5), _trade(5)]
    m = compute_metrics(trades)
    # inf is not JSON-serializable; the metrics layer must convert it.
    assert m["profit_factor"] is None


def test_sample_size_warning_appears_below_thirty_trades_and_not_above():
    below = compute_metrics([_trade(1)] * 29)
    above = compute_metrics([_trade(1)] * 30)
    assert below["sample_size_warning"] is not None
    assert above["sample_size_warning"] is None


def test_no_trades_returns_zero_without_crashing():
    m = compute_metrics([])
    assert m["num_trades"] == 0


# --- Regression: options drawdown must not assume full reinvestment ---

def _option_trade(net_return_pct):
    return OptionTrade(
        entry_date="2020-01-01", exit_date="2020-01-15", expiry_date="2020-02-01",
        option_type="CE", strike=100, spot_at_entry=100, strike_offset=0,
        entry_premium=10, exit_premium=10 * (1 + net_return_pct / 100),
        days_to_expiry_at_entry=30, holding_days=10,
        gross_return_pct=net_return_pct, cost_pct=0.0, net_return_pct=net_return_pct,
        entry_open_interest=1000,
    )


def test_realistic_drawdown_never_hits_negative_100_from_moderate_losses():
    """The bug found this session: full-reinvestment compounding through a
    sequence of large-magnitude option returns (+244%, -79%, +168%, -78%
    in real data) drove the equity curve to ~0, reporting a meaningless
    -100% drawdown even though no single trade lost more than -91%. The
    fixed calculation must keep drawdown bounded and sane for a sequence
    like that."""
    trades = [_option_trade(r) for r in [244, -79, 168, -78, -78, 1, -44, -74]]
    dd = _realistic_max_drawdown_pct(trades)
    assert dd is not None
    assert dd > -100  # must not degenerate to (near) total wipeout
    assert dd < 0     # but a real losing streak should still show as a drawdown


def test_realistic_drawdown_scales_with_position_fraction():
    trades = [_option_trade(-50), _option_trade(-50)]
    small_size = _realistic_max_drawdown_pct(trades, position_fraction=0.05)
    full_size = _realistic_max_drawdown_pct(trades, position_fraction=1.0)
    assert full_size < small_size  # betting more per trade must hurt more, not less


def test_realistic_drawdown_uses_documented_default_fraction():
    assert 0 < REALISTIC_POSITION_FRACTION <= 1


# --- Regression: hypothesis_log concurrent-write race ---

def test_hypothesis_log_survives_concurrent_writes(tmp_path, monkeypatch):
    """The bug found this session: concurrent read-modify-write on the
    shared JSON log file could interleave and corrupt it, surfacing as an
    'Extra data' JSON parse error. Fire many writes from threads at once
    and confirm the file stays valid JSON with every entry present."""
    import backtest.hypothesis_log as hl

    log_path = tmp_path / "hypothesis_log.json"
    monkeypatch.setattr(hl, "LOG_PATH", log_path)

    dummy_metrics = {"num_trades": 1, "expectancy_pct": 0.1, "profit_factor": 1.0, "max_drawdown_pct": -1.0}

    def write_one(i):
        log_run(f"strategy_{i}", {"p": i}, "^NSEI", 100, dummy_metrics)

    threads = [threading.Thread(target=write_one, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Must parse as valid JSON with exactly one entry per thread -- no
    # corruption, no silently dropped writes.
    data = json.loads(log_path.read_text())
    assert len(data) == 30
    assert total_hypotheses_tested() == 30
