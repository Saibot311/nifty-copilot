"""Transaction cost model for the index engine, which trades the index level
as a stand-in for one NIFTY futures lot. Real execution would be on NIFTY
futures, which carry their own basis and rollover costs not modeled here.

Each leg is charged in rupees on its own price and date: a discount
broker's brokerage (Zerodha's rate card, checked 2026-09-27) and the STT and
exchange charges in force that day, each from the NSE circular that set it.
The cost is then stated as a % of the notional at entry, so it subtracts
straight from the engine's gross return.
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date

# Current NIFTY lot size, the same contract lot the option research uses
# (backtest/pattern_options.py). It has changed over the years; costs use
# today's size, so they answer "what would one lot cost now" at each day's
# price. Brokerage is rupees an order, so the cost model needs it.
LOT_SIZE = 65

# Securities Transaction Tax on the sale of a futures contract, as a fraction
# of its value, from the day each rate took effect. Before the first date no
# rate was verified, and none is guessed. NIFTY's daily history starts in
# September 2007, so the first rate has to reach back that far.
STT_ON_FUTURES_SALE = (
    # 0.017% is the rate NSE's circular on the Finance Act 2013 cut from. That
    # it took effect with the Finance Act 2006 is from secondary sources.
    ("2006-06-01", 0.00017),
    ("2013-06-01", 0.0001),    # Finance Act 2013 — NSE circular of May 2013
    ("2023-04-01", 0.000125),  # Finance Act 2023 — NSE/FATAX/56235
    ("2024-10-01", 0.0002),    # Finance (No. 2) Act 2024 — NSE/FATAX/63809
    ("2026-04-01", 0.0005),    # Finance Act 2026 — NSE/FATAX/73524
)
# NSE's futures transaction charge, a fraction of value on each leg. Until
# October 2024 a volume-slab card, of which brokers passed on about Rs 190 a
# crore. Since then one rate for every member (NSE/FA/64232), Rs 173 a crore
# plus Rs 10 to NSE's IPFT — one Rs 183 charge from 2026-03-01, the same total
# (NSE/FA/73061).
EXCHANGE_CHARGE_ON_FUTURES = (
    ("2006-06-01", 0.000019),
    ("2024-10-01", 0.0000183),
)


def _in_force(schedule: tuple, day) -> float:
    """The rate in force on `day` — an ISO date string, a date or a timestamp."""
    key = str(day)[:10]
    if key < schedule[0][0]:
        raise ValueError(f"no verified rate before {schedule[0][0]} (asked for {key})")
    return schedule[bisect_right([d for d, _ in schedule], key) - 1][1]


@dataclass
class CostModel:
    """What an NSE index futures trade costs, each leg at the statutory rates
    in force on its own date and a discount broker's charges.

    Until 2026-09-27 every trade paid one flat 0.197% of notional: 0.03%
    brokerage each way, where the broker's Rs 20 cap makes it about 0.0012%
    on a NIFTY lot, and 0.02% STT whatever the date. The sale of a short was
    charged as if it were a long's.

    Not modelled: stamp duty's state rates before July 2020; service tax
    before GST (July 2017); the SEBI fee's changes over the years."""
    brokerage_pct: float = 0.0003       # 0.03% of the order's value...
    brokerage_cap_rs: float = 20.0      # ...or Rs 20 an order, whichever is lower
    gst_pct: float = 0.18               # on brokerage, exchange and SEBI charges
    sebi_fee_pct: float = 0.000001      # Rs 10 a crore, each leg
    stamp_duty_pct: float = 0.00002     # buy side only
    slippage_pct: float = 0.0005        # assumed price impact per fill, each side
    # None: each leg pays the rates in force on its own date. A date pins every
    # leg to that day's rates, to ask what a history would cost today.
    rates_as_of: str | None = None

    def stt_sell_rate(self, on: date | str) -> float:
        return _in_force(STT_ON_FUTURES_SALE, self.rates_as_of or on)

    def exchange_rate(self, on: date | str) -> float:
        return _in_force(EXCHANGE_CHARGE_ON_FUTURES, self.rates_as_of or on)

    def brokerage_rs(self, value: float) -> float:
        """One order's brokerage: a percentage, capped at a flat fee."""
        return min(value * self.brokerage_pct, self.brokerage_cap_rs)

    def _fees_rs(self, value: float, on: date | str) -> float:
        """One order's brokerage, exchange and SEBI charges, and GST on them."""
        return (self.brokerage_rs(value) + value * (self.exchange_rate(on) + self.sebi_fee_pct)) * (1 + self.gst_pct)

    def buy_cost_rs(self, price: float, quantity: int, on: date | str) -> float:
        """A purchase in rupees: `quantity` units in one order on `on`."""
        value = price * quantity
        return self._fees_rs(value, on) + value * (self.stamp_duty_pct + self.slippage_pct)

    def sell_cost_rs(self, price: float, quantity: int, on: date | str) -> float:
        """A sale in rupees: `quantity` units in one order on `on`."""
        value = price * quantity
        return self._fees_rs(value, on) + value * (self.stt_sell_rate(on) + self.slippage_pct)

    def cost_pct(self, entry_price: float, exit_price: float, entry_date: date | str, exit_date: date | str,
                 direction: str = "long", quantity: int = LOT_SIZE) -> float:
        """A trade's costs as a % of the notional at entry, each leg on its own
        price and date; one lot unless told otherwise. A long buys at entry and
        sells at exit; a short sells at entry and buys back at exit."""
        if direction == "long":
            rs = self.buy_cost_rs(entry_price, quantity, entry_date) + self.sell_cost_rs(exit_price, quantity, exit_date)
        elif direction == "short":
            rs = self.sell_cost_rs(entry_price, quantity, entry_date) + self.buy_cost_rs(exit_price, quantity, exit_date)
        else:
            raise ValueError(f"direction must be 'long' or 'short', not {direction!r}")
        return rs / (entry_price * quantity) * 100

    def round_trip_cost_pct(self, price: float, on: date | str, quantity: int = LOT_SIZE) -> float:
        """Both legs of a trade that sells at what it paid, on one day, as a %
        of notional: ~0.16% for a lot at 25,000 today. The reference figure."""
        return self.cost_pct(price, price, on, on, quantity=quantity)
