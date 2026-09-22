"""Pattern -> option research: for every registered pattern, which option
it suggests and how much that option actually made.

For each pattern, a grid of option choices is tested on real NSE contract
prices (options archive, 2018 onward):

    moneyness     ITM 2% / ITM 1% / ATM / OTM 1% / OTM 2%   (of spot, direction-aware)
    min expiry    7 / 14 / 30 calendar days out
    hold          3 / 5 / 10 trading days

The yardstick is rupees per lot — what a trader buying one lot per signal
actually makes. (Average % return was used first, and it steered almost
every pattern to the cheapest far-OTM weekly option, where a tiny premium
turns small moves into huge percentages without much money changing hands.)

Picking the best of 45 choices per pattern (1,170 in total) and reporting
its result would mostly report luck. So the option is chosen using the
DEVELOPMENT period only, and the profit that's reported as evidence comes
from the HOLDOUT period, which played no part in the choice. The verdict
then applies the same rule as index validation (I4): profitable, better
than buying that same option with no signal at all, and t >= 2.

Execution: signal on day i's close; the option is bought at day i+1's
closing premium (the archive holds one price per contract per day) and sold
at the close `hold` trading days later. Costs are applied on premium.
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .hypothesis_log import log_run
from .options_engine import run_options_backtest
from .pattern_info import PATTERN_INFO
from .strategies import STRATEGY_REGISTRY, load_daily_data
from stats.bootstrap import difference_ci, mean_ci

from .walkforward import holdout_verdict, welch_t_stat

MONEYNESS_PCT = [-2.0, -1.0, 0.0, 1.0, 2.0]  # negative = ITM, positive = OTM
MIN_DTE = [7, 14, 30]
HOLD_DAYS = [3, 5, 10]

OPTIONS_START = "2018-01-01"
SPLIT_DATE = "2024-01-01"  # ~6 years to choose on, ~2.7 years to judge on
MIN_DEV_TRADES = 10
MIN_HOLDOUT_TRADES = 15

# Current NIFTY lot size, read from Kite's instrument list on 2026-09-18.
# It has changed over the years; rupee figures use today's size so they
# answer "what would one lot make now", not what it made historically.
LOT_SIZE = 65

RESEARCH_PATH = Path(__file__).parent.parent / "data" / "pattern_options.json"


def load_research() -> dict | None:
    """The saved output of scripts/pattern_options.py, or None if never run."""
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None


def moneyness_label(m: float) -> str:
    if m == 0:
        return "ATM"
    return f"{abs(m):g}% {'ITM' if m < 0 else 'OTM'}"


def _strike_offset_pct(option_type: str, m: float) -> float:
    # A call is OTM above spot; a put is OTM below it.
    return m if option_type == "CE" else -m


def _non_overlapping(fire_idx: list[int], hold: int) -> list[int]:
    out, next_ok = [], -1
    for i in fire_idx:
        if i >= next_ok:
            out.append(i)
            next_ok = i + hold + 1  # bought at the close of i+1, sold at the close of i+1+hold
    return out


def _events_per_year(entries: pd.Series, index: pd.DatetimeIndex) -> float:
    fired = entries.astype(bool)
    starts = fired & ~fired.shift(1, fill_value=False)
    years = (index[-1] - index[0]).days / 365.25
    return round(int(starts.sum()) / years, 2) if years > 0 else 0.0


def _summarise(trades) -> dict:
    if not trades:
        return {"num_trades": 0}
    rets = [t.net_return_pct for t in trades]
    rupees = [_rupees(t) for t in trades]
    return {
        "num_trades": len(trades),
        "win_rate": round(sum(r > 0 for r in rets) / len(rets), 3),
        "avg_return_pct": round(statistics.mean(rets), 2),
        "median_return_pct": round(statistics.median(rets), 2),
        "worst_return_pct": round(min(rets), 2),
        "best_return_pct": round(max(rets), 2),
        "avg_premium": round(statistics.mean(t.entry_premium for t in trades), 2),
        "avg_profit_per_lot_rs": round(statistics.mean(rupees)),
        "total_profit_per_lot_rs": round(sum(rupees)),
    }


def _run(dates, ctx, option_type, m, dte, hold):
    df, spot, td = ctx
    return run_options_backtest(
        dates, spot, td, option_type=option_type, min_days_to_expiry=dte, hold_days=hold,
        strike_offset_pct=_strike_offset_pct(option_type, m),
    )


def _rupees(t) -> float:
    return t.entry_premium * t.net_return_pct / 100 * LOT_SIZE


def _dev(trades) -> list:
    """Development trades are the ones that *finish* before the split.

    Splitting on entry date let a trade entered in late December and exited
    in January count toward the choice of option — priced with holdout-period
    data, so the holdout helped pick the thing it was meant to judge. Trades
    that straddle the split are purged from both sides.
    """
    return [t for t in trades if t.exit_date < SPLIT_DATE]


def _holdout(trades) -> list:
    return [t for t in trades if t.entry_date >= SPLIT_DATE]


def _baseline(ctx, period_dates: list[str], option_type, m, dte, hold) -> dict:
    """Buying the same option on a fixed schedule with no signal at all.
    Keeps the trades: the significance test needs the baseline's spread,
    not just its mean."""
    dates = period_dates[:: hold + 1]
    trades = _run(dates, ctx, option_type, m, dte, hold)
    trades = _dev(trades) if period_dates and period_dates[0] < SPLIT_DATE else _holdout(trades)
    if not trades:
        return {"avg_return_pct": 0.0, "avg_profit_per_lot_rs": 0, "rupees": []}
    rupees = [_rupees(t) for t in trades]
    return {
        "avg_return_pct": round(statistics.mean(t.net_return_pct for t in trades), 2),
        "avg_profit_per_lot_rs": round(statistics.mean(rupees)),
        "rupees": rupees,
    }


def analyse_pattern(name: str, df, regime_series, ctx) -> dict:
    spec = STRATEGY_REGISTRY[name]
    option_type = spec["option_type"]
    entries = spec["fn"](df, regime_series, **spec["params"]).astype(bool)
    td = ctx[2]
    fire_idx = [i for i in range(len(df)) if entries.iloc[i] and td[i] >= OPTIONS_START]

    options_period = entries[df.index >= OPTIONS_START]
    result = {
        "strategy": name,
        "label": spec["label"],
        "direction": spec["direction"],
        "option_type": option_type,
        **PATTERN_INFO.get(name, {}),
        "forms_per_year": _events_per_year(entries, df.index),
        "forms_per_year_since_2018": _events_per_year(options_period, options_period.index),
    }

    grid = []
    for hold in HOLD_DAYS:
        dates = [td[i] for i in _non_overlapping(fire_idx, hold)]
        for dte in MIN_DTE:
            for m in MONEYNESS_PCT:
                trades = _run(dates, ctx, option_type, m, dte, hold)
                dev, hol = _dev(trades), _holdout(trades)
                dev_sum = _summarise(dev)
                log_run(f"{name}_option", {"moneyness_pct": m, "min_dte": dte, "hold_days": hold},
                        "^NSEI", 0, {"num_trades": dev_sum["num_trades"], "expectancy_pct": dev_sum.get("avg_return_pct")})
                grid.append({"m": m, "dte": dte, "hold": hold, "dev": dev_sum, "holdout": _summarise(hol),
                             "_holdout_trades": hol})

    eligible = [g for g in grid if g["dev"]["num_trades"] >= MIN_DEV_TRADES]
    result["configs_tested"] = len(grid)
    if not eligible:
        result.update(status="REJECTED", reason=f"Fewer than {MIN_DEV_TRADES} option trades in the development period for every choice — too rare to judge.")
        return result

    best = max(eligible, key=lambda g: g["dev"]["avg_profit_per_lot_rs"])
    m, dte, hold = best["m"], best["dte"], best["hold"]
    all_days = [d for d in td if d >= OPTIONS_START]
    dev_days = [d for d in all_days if d < SPLIT_DATE]
    hol_days = [d for d in all_days if d >= SPLIT_DATE]
    dev_base = _baseline(ctx, dev_days, option_type, m, dte, hold)
    hol_base = _baseline(ctx, hol_days, option_type, m, dte, hold)

    hol_rs = [_rupees(t) for t in best["_holdout_trades"]]
    t_stat = welch_t_stat(hol_rs, hol_base["rupees"])
    status, reason = holdout_verdict(
        best["dev"]["avg_profit_per_lot_rs"], best["holdout"].get("avg_profit_per_lot_rs") or 0,
        dev_base["avg_profit_per_lot_rs"], hol_base["avg_profit_per_lot_rs"],
        best["holdout"]["num_trades"], MIN_HOLDOUT_TRADES, spec["direction"], t_stat,
        baseline_label=f"buying this {option_type} with no signal", unit="₹",
    )

    trades_detail = [{"entry_date": t.entry_date, "exit_date": t.exit_date, "expiry": t.expiry_date,
                      "strike": t.strike, "entry_premium": t.entry_premium, "exit_premium": t.exit_premium,
                      "net_return_pct": t.net_return_pct, "profit_per_lot_rs": round(_rupees(t))}
                     for t in best["_holdout_trades"]]
    result.update(
        holdout_ci_95=mean_ci(hol_rs),
        edge_over_no_signal_ci_95=difference_ci(hol_rs, hol_base["rupees"]),
        holdout_trades_detail=trades_detail,
        suggested_option={
            "type": option_type,
            "moneyness_pct": m,
            "moneyness": moneyness_label(m),
            "min_days_to_expiry": dte,
            "hold_days": hold,
            "description": f"Buy {moneyness_label(m)} {option_type}, expiry at least {dte} days out, hold {hold} trading days",
        },
        development=best["dev"],
        holdout=best["holdout"],
        baseline={
            "development_avg_return_pct": dev_base["avg_return_pct"],
            "holdout_avg_return_pct": hol_base["avg_return_pct"],
            "development_avg_profit_per_lot_rs": dev_base["avg_profit_per_lot_rs"],
            "holdout_avg_profit_per_lot_rs": hol_base["avg_profit_per_lot_rs"],
        },
        holdout_t_stat=t_stat,
        status=status,
        reason=reason,
    )
    return result


def run_pattern_options(symbol: str = "^NSEI") -> dict:
    df, regime_series = load_daily_data(symbol, 7000)
    td = [str(d.date()) for d in df.index]
    ctx = (df, pd.Series(df["close"].values, index=td), td)

    patterns = [analyse_pattern(name, df, regime_series, ctx) for name in STRATEGY_REGISTRY]
    rank = {"APPROVED": 0, "CONDITIONAL": 1, "REJECTED": 2}
    patterns.sort(key=lambda p: (rank[p["status"]], -((p.get("holdout") or {}).get("avg_profit_per_lot_rs") or -1e9)))

    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "options_period": {"start": OPTIONS_START, "split": SPLIT_DATE, "end": td[-1]},
        "lot_size": LOT_SIZE,
        "grid": {"moneyness_pct": MONEYNESS_PCT, "min_days_to_expiry": MIN_DTE, "hold_days": HOLD_DAYS},
        "configs_tested_total": sum(p.get("configs_tested", 0) for p in patterns),
        "patterns": patterns,
        "method_note": (
            "Each pattern's option was chosen by average rupee profit per lot on 2018-2023 data only; the "
            "profit shown as evidence is from 2024 onward, which played no part in the choice. APPROVED requires "
            "that holdout profit per lot to beat buying the same option with no signal, with t >= 2. Premiums are real NSE closing prices; bought at "
            "the close the day after the signal. Rupee figures use today's lot size of "
            f"{LOT_SIZE}."
        ),
    }
