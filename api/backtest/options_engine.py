"""Backtests what an actual OPTION position would have returned when a
signal fired — not what the index did.

This is the difference that matters for options trading. An index
backtest saying "+0.61% per trade" tells you nothing about whether a call
option bought on that signal made money: the option also pays theta every
day, and can lose even when the index moves the right way but too slowly.

Prices come from the local NSE bhavcopy archive (settlement/close per
strike per day). Spot comes from the same daily series the signals are
computed on, so strike selection matches what a trader would have seen.

Two honest limitations, stated because they materially affect results:
  1. Bhavcopy gives close/settle prices, not bid/ask. Real fills happen
     at the spread, which on options is proportionally large. The cost
     model charges a configurable premium slippage for this, but the true
     figure varies with strike liquidity and can be worse than modeled.
  2. An untraded strike still gets a settlement price in bhavcopy. Trading
     it would have been impossible at that number, so contracts below a
     liquidity floor are rejected rather than silently used.
"""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from storage import connect


@dataclass
class OptionsCostModel:
    """Approximate NSE index-options costs. Percentages apply to PREMIUM,
    not notional — options costs scale with premium, which is why they bite
    so much harder proportionally than futures costs do."""
    brokerage_pct: float = 0.0003      # discount-broker flat fee, approximated as % of premium
    stt_pct_sell: float = 0.001        # STT on sell-side premium
    exchange_txn_pct: float = 0.0005   # NSE options transaction charges (much higher than futures)
    gst_pct: float = 0.18
    stamp_duty_pct: float = 0.00003    # buy side only
    premium_slippage_pct: float = 0.015  # bid-ask reality, each side

    def round_trip_cost_fraction(self) -> float:
        """Total cost as a fraction of premium paid, for one buy + one sell."""
        buy = self.brokerage_pct + self.exchange_txn_pct + self.stamp_duty_pct + self.premium_slippage_pct
        sell = self.brokerage_pct + self.exchange_txn_pct + self.stt_pct_sell + self.premium_slippage_pct
        gst = self.gst_pct * (2 * self.brokerage_pct + 2 * self.exchange_txn_pct)
        return buy + sell + gst


@dataclass
class OptionTrade:
    entry_date: str
    exit_date: str
    expiry_date: str
    option_type: str
    strike: float
    spot_at_entry: float
    strike_offset: float          # strike - spot, negative = ITM for a call
    entry_premium: float
    exit_premium: float
    days_to_expiry_at_entry: int
    holding_days: int
    gross_return_pct: float       # on premium
    cost_pct: float
    net_return_pct: float
    entry_open_interest: float


def _nearest_strike(strikes: list[float], target: float) -> float | None:
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s - target))


def select_contract(
    trade_date: str,
    spot: float,
    option_type: str,
    strike_offset_pts: float,
    min_days_to_expiry: int,
    must_survive_until: str,
    min_open_interest: float,
    conn,
) -> tuple[float, str] | None:
    """Picks (strike, expiry) as a trader would on `trade_date`.

    Requires the expiry to outlast the planned exit (`must_survive_until`)
    so the position isn't silently expiring mid-trade, and requires real
    open interest so we aren't pricing off an untradeable stale quote.
    """
    rows = conn.execute(
        """SELECT DISTINCT expiry_date FROM option_bars
           WHERE trade_date = ? AND expiry_date > ?
           ORDER BY expiry_date""",
        (trade_date, must_survive_until),
    ).fetchall()

    entry = date.fromisoformat(trade_date)
    for row in rows:
        expiry = row["expiry_date"]
        if (date.fromisoformat(expiry) - entry).days < min_days_to_expiry:
            continue

        strike_rows = conn.execute(
            """SELECT strike, open_interest FROM option_bars
               WHERE trade_date = ? AND expiry_date = ? AND option_type = ?
                 AND open_interest >= ? AND close > 0""",
            (trade_date, expiry, option_type, min_open_interest),
        ).fetchall()
        strikes = [r["strike"] for r in strike_rows]
        chosen = _nearest_strike(strikes, spot + strike_offset_pts)
        if chosen is not None:
            return chosen, expiry
    return None


def run_options_backtest(
    signal_dates: list[str],
    spot_series: pd.Series,
    trading_days: list[str],
    option_type: str = "CE",
    strike_offset_pts: float = 0.0,
    min_days_to_expiry: int = 25,
    hold_days: int = 10,
    min_open_interest: float = 1000,
    cost_model: OptionsCostModel | None = None,
    strike_offset_pct: float | None = None,
    db_path=None,
) -> list[OptionTrade]:
    """For each signal date, buy one option and hold it `hold_days` trading
    days. Entry is at the *close* of the session after the signal: the
    archive is end-of-day, and a close is the one option price it records
    reliably. That is one session later than the index engine's next-open
    entry — never earlier, so never lookahead — and the research states it.

    A trade that cannot run its full hold before the data ends is dropped.
    It used to be closed early and counted as complete, which would have put
    a 2-day result into a 10-day statistic for the newest signals — the
    holdout runs to today, so exactly the trades that decide verdicts.

    `strike_offset_pct`, if given, overrides `strike_offset_pts` with a
    per-trade offset of that % of spot, so "1% OTM" means the same thing in
    2018 (spot ~10k) as in 2026 (spot ~23k)."""
    cost_model = cost_model or OptionsCostModel()
    cost_fraction = cost_model.round_trip_cost_fraction()
    day_index = {d: i for i, d in enumerate(trading_days)}

    trades: list[OptionTrade] = []
    with connect(db_path) as conn:  # None is the NIFTY archive; see storage.options_db.db_path_for
        for signal_date in signal_dates:
            i = day_index.get(signal_date)
            if i is None or i + 1 >= len(trading_days):
                continue

            entry_date = trading_days[i + 1]
            exit_idx = i + 1 + hold_days
            if exit_idx >= len(trading_days):
                continue  # cannot complete its hold yet
            exit_date = trading_days[exit_idx]

            spot = spot_series.get(entry_date)
            if spot is None or pd.isna(spot):
                continue

            offset = float(spot) * strike_offset_pct / 100 if strike_offset_pct is not None else strike_offset_pts
            picked = select_contract(
                entry_date, float(spot), option_type, offset,
                min_days_to_expiry, exit_date, min_open_interest, conn,
            )
            if picked is None:
                continue
            strike, expiry = picked

            entry_row = conn.execute(
                """SELECT close, open_interest FROM option_bars
                   WHERE trade_date=? AND expiry_date=? AND strike=? AND option_type=?""",
                (entry_date, expiry, strike, option_type),
            ).fetchone()
            exit_row = conn.execute(
                """SELECT close FROM option_bars
                   WHERE trade_date=? AND expiry_date=? AND strike=? AND option_type=?""",
                (exit_date, expiry, strike, option_type),
            ).fetchone()

            if not entry_row or not exit_row:
                continue
            entry_premium = float(entry_row["close"])
            exit_premium = float(exit_row["close"])
            if entry_premium <= 0:
                continue

            gross = (exit_premium - entry_premium) / entry_premium * 100
            cost = cost_fraction * 100
            trades.append(OptionTrade(
                entry_date=entry_date,
                exit_date=exit_date,
                expiry_date=expiry,
                option_type=option_type,
                strike=strike,
                spot_at_entry=round(float(spot), 2),
                strike_offset=round(strike - float(spot), 2),
                entry_premium=round(entry_premium, 2),
                exit_premium=round(exit_premium, 2),
                days_to_expiry_at_entry=(date.fromisoformat(expiry) - date.fromisoformat(entry_date)).days,
                holding_days=exit_idx - (i + 1),
                gross_return_pct=round(gross, 2),
                cost_pct=round(cost, 3),
                net_return_pct=round(gross - cost, 2),
                entry_open_interest=float(entry_row["open_interest"]),
            ))

    return trades
