"""Core trade simulator. One rule, strictly enforced: a decision made using
data through bar i is only ever executed at bar i+1's open — never at bar
i's own close. That single rule is what makes this immune to lookahead
bias; every signal function must respect it (signals are computed from
already-closed bars, entry always happens one bar later).

Positions are non-overlapping (one trade at a time) — deliberately simple
for a first engine. No pyramiding, no concurrent strategies.
"""

from dataclasses import dataclass

import pandas as pd

from .costs import CostModel


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    direction: str  # "long" | "short"
    entry_price: float
    exit_price: float
    regime_at_entry: str
    holding_days: int
    gross_return_pct: float
    cost_pct: float
    net_return_pct: float


def run_backtest(
    df: pd.DataFrame,
    entry_signal: pd.Series,
    regime_series: pd.Series,
    direction: str = "long",
    hold_days: int = 10,
    cost_model: CostModel | None = None,
) -> list[Trade]:
    if len(df) != len(entry_signal) or len(df) != len(regime_series):
        raise ValueError("df, entry_signal, and regime_series must be the same length and aligned.")

    cost_model = cost_model or CostModel()
    round_trip_cost = cost_model.round_trip_cost_pct()
    sign = 1 if direction == "long" else -1

    trades: list[Trade] = []
    n = len(df)
    i = 0
    while i < n - 1:
        # entry_signal.iloc[i] is decided using only data through bar i (the
        # signal functions guarantee this); we execute at i+1's open, never
        # at bar i's own close.
        if bool(entry_signal.iloc[i]):
            entry_idx = i + 1
            if entry_idx >= n:
                break
            exit_idx = min(entry_idx + hold_days, n - 1)

            entry_price = float(df["open"].iloc[entry_idx])
            exit_price = float(df["close"].iloc[exit_idx])
            gross_return_pct = (exit_price - entry_price) / entry_price * 100 * sign
            net_return_pct = gross_return_pct - round_trip_cost

            trades.append(Trade(
                entry_date=str(df.index[entry_idx].date()),
                exit_date=str(df.index[exit_idx].date()),
                direction=direction,
                entry_price=round(entry_price, 2),
                exit_price=round(exit_price, 2),
                regime_at_entry=str(regime_series.iloc[i]),
                holding_days=exit_idx - entry_idx,
                gross_return_pct=round(gross_return_pct, 3),
                cost_pct=round(round_trip_cost, 3),
                net_return_pct=round(net_return_pct, 3),
            ))
            i = exit_idx + 1
            continue
        i += 1

    return trades
