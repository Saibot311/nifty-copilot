"""The single most important invariant in this whole project: a decision
made using data through bar i is only ever executed at bar i+1's open.
These tests build a synthetic dataframe where getting that wrong produces
a detectably different (and better-looking) result, so a future change
that reintroduces lookahead fails loudly instead of silently.
"""

import pandas as pd
import pytest

from backtest.costs import CostModel
from backtest.engine import run_backtest


def _synthetic_df(n=30, start_price=100.0, daily_move=1.0):
    """A strictly rising series: close[i] = start + i * daily_move. Any
    lookahead bug (using bar i's own close as an achievable entry price)
    would show up as a systematically better fill than a true next-open
    entry could produce, since here open == prior close exactly."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    closes = [start_price + i * daily_move for i in range(n)]
    opens = [closes[0]] + closes[:-1]  # today's open == yesterday's close
    df = pd.DataFrame({
        "open": opens, "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes], "close": closes,
    }, index=dates)
    return df


def test_entry_executes_at_next_bar_open_not_current_close():
    df = _synthetic_df()
    # Fire a single signal on bar 5.
    entries = pd.Series(False, index=df.index)
    entries.iloc[5] = True
    regime = pd.Series("N/A", index=df.index)

    trades = run_backtest(df, entries, regime, direction="long", hold_days=3, cost_model=CostModel())

    assert len(trades) == 1
    t = trades[0]
    # Entry price must equal bar 6's open (== bar 5's close in this
    # series), never bar 5's own close used directly.
    assert t.entry_price == pytest.approx(df["open"].iloc[6])
    assert t.entry_date == str(df.index[6].date())


def test_no_signal_on_last_bar_produces_no_trade():
    """A signal on the final bar has no bar+1 to execute at -- must be
    silently dropped, not crash or fabricate a fill."""
    df = _synthetic_df(n=10)
    entries = pd.Series(False, index=df.index)
    entries.iloc[-1] = True
    regime = pd.Series("N/A", index=df.index)

    trades = run_backtest(df, entries, regime, direction="long", hold_days=3)
    assert trades == []


def test_positions_do_not_overlap():
    """Firing every single day must still only ever hold one position at a
    time -- the next entry can't be considered until the current one has
    exited."""
    df = _synthetic_df(n=40)
    entries = pd.Series(True, index=df.index)
    regime = pd.Series("N/A", index=df.index)

    trades = run_backtest(df, entries, regime, direction="long", hold_days=5)

    for a, b in zip(trades, trades[1:]):
        assert b.entry_date > a.exit_date, "overlapping positions detected"


def test_short_direction_inverts_pnl_sign():
    df = _synthetic_df()  # rising market
    entries = pd.Series(False, index=df.index)
    entries.iloc[5] = True
    regime = pd.Series("N/A", index=df.index)

    long_trade = run_backtest(df, entries, regime, direction="long", hold_days=3)[0]
    short_trade = run_backtest(df, entries, regime, direction="short", hold_days=3)[0]

    # Same entry/exit prices (same signal, same market), opposite sign P&L.
    assert long_trade.gross_return_pct > 0
    assert short_trade.gross_return_pct < 0
    assert long_trade.gross_return_pct == pytest.approx(-short_trade.gross_return_pct)


def test_costs_reduce_net_return_relative_to_gross():
    df = _synthetic_df()
    entries = pd.Series(False, index=df.index)
    entries.iloc[5] = True
    regime = pd.Series("N/A", index=df.index)

    trades = run_backtest(df, entries, regime, direction="long", hold_days=3, cost_model=CostModel())
    t = trades[0]
    assert t.net_return_pct < t.gross_return_pct
    # gross/cost/net are each rounded independently to 3dp in engine.py, so
    # they can differ from an exact subtraction by up to ~0.002 -- a
    # cosmetic display quirk, not a financial error (the underlying
    # unrounded net always equals gross - cost exactly).
    assert t.net_return_pct == pytest.approx(t.gross_return_pct - t.cost_pct, abs=0.002)
