"""Transaction cost model for NSE index-futures-style intraday/positional
trading. Defaults are indicative approximations of published NSE/broker
rate cards as of 2025-26 — verify against a current rate card before
trusting the absolute numbers; the point of this module is that costs are
modeled explicitly and configurably at all, not that these exact basis
points are precise or will stay accurate over time.

This backtest simulates trading the index level directly, as a stand-in
for a real futures/ETF position. Real execution would be on NIFTY futures,
which carry their own basis and rollover costs not modeled here.
"""

from dataclasses import dataclass


@dataclass
class CostModel:
    brokerage_pct: float = 0.0003       # ~0.03% per executed order (approx flat-fee brokers)
    stt_pct: float = 0.0002             # securities transaction tax, sell side only, futures
    exchange_txn_pct: float = 0.000019  # NSE F&O transaction charges
    gst_pct: float = 0.18               # GST on (brokerage + exchange charges)
    stamp_duty_pct: float = 0.00002     # buy side only
    slippage_pct: float = 0.0005        # assumed price impact per fill, each side

    def round_trip_cost_pct(self) -> float:
        """Total cost of one entry + one exit, as a percentage of notional."""
        buy_side = self.brokerage_pct + self.exchange_txn_pct + self.stamp_duty_pct + self.slippage_pct
        sell_side = self.brokerage_pct + self.exchange_txn_pct + self.stt_pct + self.slippage_pct
        gst = self.gst_pct * (2 * self.brokerage_pct + 2 * self.exchange_txn_pct)
        return (buy_side + sell_side + gst) * 100  # returned as a percentage, e.g. 0.18 == 0.18%
