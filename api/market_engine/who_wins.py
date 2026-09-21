"""Who makes money in NIFTY options, measured on this system's own data.

Every option is a contract between a buyer and a seller, so before costs
one side's gain is the other's loss. SEBI's studies say where the money
goes: most individuals lose, and proprietary desks and foreign institutions
— nearly all of it through algorithms — take it. The mechanism most within
reach of measurement here is the variance risk premium (Carr & Wu 2009):
options are priced for more movement than usually arrives, because buyers
pay for protection and for the chance of a large move. A seller collects
that gap most months and pays out in the crashes; a buyer pays it.

So: 30-day implied volatility on each day, against the volatility NIFTY
actually delivered over the following 21 sessions (about 30 calendar days).

The historical comparison uses the future by construction — that is what
"delivered" means — so it is a study of the past, never shown as a signal.
The *current* reading compares today's implied volatility with the
volatility of the last 21 sessions, which is already known.
"""

import math
import statistics

import numpy as np
import pandas as pd

from backtest.iv_research import load_series
from backtest.pattern_options import load_research
from backtest.strategies import load_daily_data

HORIZON = 21  # trading sessions in ~30 calendar days


def _realised(returns: np.ndarray) -> float:
    """Annualised realised volatility, in vol points. Root mean square rather
    than standard deviation — the convention for variance claims, and the
    one an option's payoff actually follows."""
    return math.sqrt(252 * float(np.mean(returns ** 2))) * 100


def _frame() -> pd.DataFrame:
    df, _ = load_daily_data("^NSEI", 7000)
    closes = pd.Series(df["close"].values, index=[str(i.date()) for i in df.index])
    logret = np.log(closes).diff()
    iv = load_series()["iv_30d"] * 100
    rows = []
    dates = list(closes.index)
    pos = {d: i for i, d in enumerate(dates)}
    for d, v in iv.dropna().items():
        i = pos.get(d)
        if i is None or i < HORIZON:
            continue
        past = logret.iloc[i - HORIZON + 1:i + 1].to_numpy()
        fut = logret.iloc[i + 1:i + 1 + HORIZON].to_numpy() if i + HORIZON < len(dates) else None
        rows.append({"date": d, "iv": v, "rv_past": _realised(past),
                     "rv_next": _realised(fut) if fut is not None and len(fut) == HORIZON else None})
    return pd.DataFrame(rows).set_index("date")


def variance_risk_premium() -> dict:
    f = _frame()
    done = f.dropna(subset=["rv_next"])
    gap = done["iv"] - done["rv_next"]
    by_year = {}
    for yr, g in done.groupby(done.index.str[:4]):
        by_year[yr] = {"days": len(g), "avg_implied": round(float(g["iv"].mean()), 1),
                       "avg_delivered": round(float(g["rv_next"].mean()), 1),
                       "options_overpriced_share": round(float((g["iv"] > g["rv_next"]).mean()), 2)}
    worst = gap.nsmallest(5)
    latest = f.iloc[-1]
    return {
        "days": len(done),
        "period": f"{done.index[0]} to {done.index[-1]}",
        "avg_implied": round(float(done["iv"].mean()), 1),
        "avg_delivered": round(float(done["rv_next"].mean()), 1),
        "median_gap_points": round(float(gap.median()), 1),
        "mean_gap_points": round(float(gap.mean()), 1),
        "options_overpriced_share": round(float((gap > 0).mean()), 2),
        "by_year": by_year,
        "when_sellers_were_hurt": [
            {"date": d, "implied": round(float(done.loc[d, "iv"]), 1),
             "delivered": round(float(done.loc[d, "rv_next"]), 1)} for d in worst.index],
        "now": {
            "date": f.index[-1],
            "implied": round(float(latest["iv"]), 1),
            "delivered_last_21_sessions": round(float(latest["rv_past"]), 1),
            "note": ("Today's implied volatility against what the index actually moved over the past 21 sessions "
                     "— both already known. Whether the next month delivers more or less is unknown."),
        },
        "note": ("Implied: 30-day at-the-money implied volatility from NSE closing prices. Delivered: the "
                 "annualised volatility NIFTY actually showed over the next 21 sessions. When implied exceeds "
                 "delivered, option buyers paid for movement that did not come. A study of the past only."),
    }


def buyers_without_a_signal() -> dict:
    """The option research already prices buying each pattern's option on a
    fixed schedule, with no signal at all. That is the cost of simply being
    an option buyer here."""
    rs = [p["baseline"]["holdout_avg_profit_per_lot_rs"] for p in (load_research() or {}).get("patterns", [])
          if (p.get("baseline") or {}).get("holdout_avg_profit_per_lot_rs") is not None]
    if not rs:
        return {"available": False}
    return {"available": True, "setups": len(rs),
            "median_rupees_per_lot": round(statistics.median(rs)),
            "setups_that_made_money": sum(1 for r in rs if r > 0),
            "note": ("Buying each pattern's chosen option on a fixed schedule over 2024-26, no signal, after "
                     "costs. This is what the patterns had to beat — and what an option buyer pays on average "
                     "for simply being one.")}


# Published facts, with sources. Numbers here are SEBI's, not this system's.
SEBI_FACTS = {
    "fy22_fy24": {"share_of_individuals_losing": "93%", "aggregate_loss": "₹1.8 lakh crore over three years",
                  "average_loss": "about ₹2 lakh per loss-making trader",
                  "profitable_over_1_lakh_after_costs": "about 1%",
                  "source": "SEBI study, September 2024",
                  "url": "https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html"},
    "fy24_winners": {"proprietary_gross_profit": "₹33,000 crore", "fpi_gross_profit": "₹28,000 crore",
                     "share_via_algorithms": "96% (proprietary) and 97% (FPIs)",
                     "source": "SEBI study, September 2024"},
    "fy25": {"share_of_individuals_losing": "91%", "aggregate_net_loss": "₹1,05,603 crore",
             "source": "SEBI study, July 2025 (as reported by Business Standard)",
             "url": "https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html"},
    "fy26": {"share_of_individuals_losing": "87.7%", "aggregate_net_loss": "₹91,685 crore",
             "average_net_loss": "₹1.17 lakh", "share_of_losses_from_options": "92%",
             "index_options_turnover_on_expiry_day_contracts": "about 59%",
             "transaction_costs": "about ₹25,000 crore",
             "source": "SEBI study, August 2026",
             "url": "https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html"},
}
