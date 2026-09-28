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

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date

import pandas as pd

from storage import connect


# Current NIFTY lot size, read from Kite's instrument list on 2026-09-18.
# It has changed over the years; rupee figures use today's size so they
# answer "what would one lot make now", not what it made historically. The
# cost model charges brokerage per order, so it needs it too.
LOT_SIZE = 65
# Today's lot on the other indices the research replicates on, by the same
# convention: NSE's F&O lot file (fo_mktlots.csv) for BANKNIFTY and MIDCPNIFTY,
# checked 2026-09-27; SENSEX, a BSE contract, from brokers' notices of BSE's
# October 2024 revision.
LOT_SIZES = {"NIFTY": LOT_SIZE, "BANKNIFTY": 30, "MIDCPNIFTY": 120, "SENSEX": 20}


# When the cost model's rates were last checked against the broker's and the
# exchange's. Anything stored from its output is keyed by it, so a change to
# the model cannot leave a cached result on the old one.
COSTS_VERSION = "2026-09-27"

# Securities Transaction Tax on the sale of an option, as a fraction of the
# premium, from the day each rate took effect — each from the NSE circular that
# announced it. Before the first date no rate was verified, and none is guessed.
STT_ON_OPTION_SALE = (
    ("2014-10-01", 0.00017),   # set in 2008; restated by NSE/FATAX/27711
    ("2016-06-01", 0.0005),    # Finance Act 2016 — NSE/FATAX/32385
    ("2023-04-01", 0.000625),  # Finance Act 2023 — NSE/FATAX/56235
    ("2024-10-01", 0.001),     # Finance (No. 2) Act 2024 — NSE/FATAX/63809
    ("2026-04-01", 0.0015),    # Finance Act 2026 — NSE/FATAX/73524
)
# NSE's options transaction charge, a fraction of premium on each leg. Until
# October 2024 a volume-slab card, of which brokers passed on about Rs 50 a lakh
# (Rs 53 from 2021 to March 2023: 0.003%, not modelled). Since then one rate for
# every member (NSE/FA/64232), Rs 3,503 a crore plus Rs 50 to NSE's IPFT — one
# Rs 3,553 charge from 2026-03-01, the same total (NSE/FA/73061).
EXCHANGE_CHARGE_ON_OPTIONS = (
    ("2014-10-01", 0.0005),
    ("2024-10-01", 0.0003553),
)


def _in_force(schedule: tuple, day) -> float:
    """The rate in force on `day` — an ISO date string, a date or a timestamp."""
    key = str(day)[:10]
    if key < schedule[0][0]:
        raise ValueError(f"no verified rate before {schedule[0][0]} (asked for {key})")
    return schedule[bisect_right([d for d, _ in schedule], key) - 1][1]


@dataclass
class OptionsCostModel:
    """What an NSE index option costs a buyer, each leg at the statutory rates
    in force on its own date and a discount broker's charges (Zerodha's rate
    card, checked 2026-09-27). Brokerage is rupees an order; everything else
    scales with premium, so costs bite hardest on a cheap option.

    Until 2026-09-27 brokerage was 0.03% of premium and STT and the exchange
    charge were fixed at 0.10% and 0.05%: about Rs 19 a lot at a Rs 100
    premium, before slippage, where the published rates come to about Rs 63.

    Not modelled: STT on an option held to expiry and exercised (0.125% of
    intrinsic value, 0.15% from 2026-04-01), since nothing here holds to
    expiry; stamp duty's state rates before July 2020; an order split at the
    exchange's freeze quantity."""
    brokerage_per_order_rs: float = 20.0
    gst_pct: float = 0.18                # on brokerage, exchange and SEBI charges
    sebi_fee_pct: float = 0.000001       # Rs 10 a crore, each leg
    stamp_duty_pct: float = 0.00003      # buy side only
    premium_slippage_pct: float = 0.015  # bid-ask reality, each side
    # None: each leg pays the rates in force on its own date. A date pins every
    # leg to that day's rates, to ask what a history would cost today.
    rates_as_of: str | None = None

    def stt_sell_rate(self, on: date | str) -> float:
        return _in_force(STT_ON_OPTION_SALE, self.rates_as_of or on)

    def exchange_rate(self, on: date | str) -> float:
        return _in_force(EXCHANGE_CHARGE_ON_OPTIONS, self.rates_as_of or on)

    def _fees_rs(self, value: float, on: date | str) -> float:
        """One order's brokerage, exchange and SEBI charges, and GST on them."""
        return (self.brokerage_per_order_rs + value * (self.exchange_rate(on) + self.sebi_fee_pct)) * (1 + self.gst_pct)

    def buy_cost_rs(self, premium: float, quantity: int, on: date | str) -> float:
        """The buying leg in rupees: `quantity` units in one order on `on`."""
        value = premium * quantity
        return self._fees_rs(value, on) + value * (self.stamp_duty_pct + self.premium_slippage_pct)

    def sell_cost_rs(self, premium: float, quantity: int, on: date | str) -> float:
        """The selling leg in rupees — STT, slippage, fees — on what it sold
        for. A sale that would cost more than it fetches is not made: the buyer
        lets the option lapse, paying nothing and receiving nothing."""
        value = premium * quantity
        cost = self._fees_rs(value, on) + value * (self.stt_sell_rate(on) + self.premium_slippage_pct)
        return min(cost, value)

    def round_trip_cost_fraction(self, premium: float, on: date | str, quantity: int = LOT_SIZE) -> float:
        """Both legs of a trade that sells at what it paid, as a fraction of
        premium: ~4% for a lot at Rs 100 today. The reference figure, and the
        sizing reserve."""
        return (self.buy_cost_rs(premium, quantity, on) + self.sell_cost_rs(premium, quantity, on)) \
            / (premium * quantity)

    def summary(self, on: date | str) -> str:
        """The rate card in force on `on`, in words, for a page to state."""
        pct = lambda f: f"{f * 100:.3g}%"  # noqa: E731
        card = (f"₹{self.brokerage_per_order_rs:g} an order plus {pct(self.gst_pct)} GST, "
                f"{pct(self.stt_sell_rate(on))} STT on the sale, {pct(self.exchange_rate(on))} exchange charges")
        # A model given the real spread charges no slippage, and says none.
        return f"{card} and {pct(self.premium_slippage_pct)} slippage each way" if self.premium_slippage_pct else card

    def cost_pct(self, entry_premium: float, exit_premium: float, entry_date: date | str, exit_date: date | str,
                 quantity: int = LOT_SIZE) -> float:
        """A trade's actual costs as a % of the premium paid, each leg on its
        own premium and date; one lot unless told otherwise. Until 2026-09-24
        the whole round trip was charged on the entry premium, so a trade that
        tripled paid a third of its real exit costs and one that expired
        worthless paid exit costs on a sale that never happened."""
        return (self.buy_cost_rs(entry_premium, quantity, entry_date)
                + self.sell_cost_rs(exit_premium, quantity, exit_date)) / (entry_premium * quantity) * 100


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
    quantity: int = LOT_SIZE,
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
    2018 (spot ~10k) as in 2026 (spot ~23k).

    `quantity` is the units in each order — one lot of the archive's index —
    which a flat per-order brokerage needs to be a share of the premium."""
    cost_model = cost_model or OptionsCostModel()
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
            cost = cost_model.cost_pct(entry_premium, exit_premium, entry_date, exit_date, quantity)
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
