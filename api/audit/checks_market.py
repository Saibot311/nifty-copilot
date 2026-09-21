"""The market context engine: positioning data integrity, no look-ahead in
the attribution or the "now" readings, and whether the unusual-activity
monitor cries wolf."""

import numpy as np
import pandas as pd

from . import FAIL, PASS, SKIP, WARN, Result, check


@check("M", "M.1", "Participant positioning balances — every long is someone's short — and covers every session")
def participant_zero_sum():
    from market_data.bar_archive import index_trading_days
    from market_engine.positioning import ZERO_SUM_TOLERANCE, by_day, zero_sum_check
    days = by_day()
    if not days:
        return Result(SKIP, "no participant data yet")
    worst = max((abs(g), d, k) for d, v in days.items() for k, g in zero_sum_check(v).items())
    sessions, _ = index_trading_days()
    wanted = {d for d in sessions if min(days) <= d <= max(days)}
    missing = sorted(wanted - set(days))
    status = FAIL if worst[0] > ZERO_SUM_TOLERANCE else (WARN if missing else PASS)
    return Result(status, f"{len(days)} sessions; largest long-short gap {worst[0]} contract(s) ({worst[1]}, "
                          f"{worst[2]}) against a rounding tolerance of {ZERO_SUM_TOLERANCE}; "
                          f"{len(missing)} session(s) missing", {"missing": missing[:10]})


@check("M", "M.2", "Every global cue used to explain a day closed before India opened that day")
def global_cues_are_prior():
    from market_engine import drivers
    from market_engine.drivers import FACTORS, _returns
    from datetime import date
    frame = drivers.load_frame()
    india = frame.nifty.index
    late = {}
    for k, (ticker, _) in FACTORS.items():
        src = _returns(ticker, date(2015, 1, 1))
        # Replace each value with its own date's ordinal: what comes back is
        # the date actually used, which must precede the Indian date.
        dated = pd.Series([d.toordinal() for d in src.index], index=src.index, dtype=float)
        used = drivers.prior_session(dated, india)
        bad = [(str(d.date()), str(pd.Timestamp.fromordinal(int(u)).date()))
               for d, u in used.items() if not np.isnan(u) and u >= d.toordinal()]
        if bad:
            late[k] = bad[:5]
    return Result(FAIL if late else PASS, f"{len(india)} Indian sessions x {len(FACTORS)} factors; "
                                          f"{sum(len(v) for v in late.values())} used a same-day or later session",
                  {"late": late})


@check("M", "M.3", "The 'now' volatility reading uses only sessions already closed")
def vrp_now_uses_past_only():
    from backtest.strategies import load_daily_data
    from market_engine.who_wins import HORIZON, _realised, variance_risk_premium
    now = variance_risk_premium()["now"]
    df, _ = load_daily_data("^NSEI", 7000)
    closes = pd.Series(df["close"].values, index=[str(i.date()) for i in df.index])
    upto = closes.loc[:now["date"]]
    expected = round(_realised(np.log(upto).diff().iloc[-HORIZON:].to_numpy()), 1)
    ok = expected == now["delivered_last_21_sessions"]
    return Result(PASS if ok else FAIL, f"recomputed from data ending {now['date']}: {expected} vs reported "
                                        f"{now['delivered_last_21_sessions']}")


@check("M", "M.4", "The unusual-activity monitor does not cry wolf")
def unusual_activity_false_alarms():
    """A flag that fires most days carries no information. Measured over the
    last 20 archived sessions, which are ordinary sessions for the most part."""
    import sqlite3

    from market_engine.expiry import unusual_option_activity
    from storage.options_db import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    days = [r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM option_bars ORDER BY trade_date DESC LIMIT 20")]
    conn.close()
    runs = [unusual_option_activity(as_of=d, top=50) for d in days]
    flagged = [r["date"] for r in runs if r.get("available") and r["unusual"]]
    n = sum(1 for r in runs if r.get("available"))
    share = len(flagged) / n if n else 0
    return Result(WARN if share > 0.2 else PASS,
                  f"{len(flagged)} of {n} recent sessions raised a flag ({share:.0%}); above 20% a flag stops meaning much",
                  {"flagged": flagged})


@check("M", "M.5", "Every principle and every SEBI figure the engine quotes carries its source")
def knowledge_sourced():
    from market_engine.knowledge import KNOWLEDGE
    from market_engine.who_wins import SEBI_FACTS
    unsourced = [k["id"] for k in KNOWLEDGE if not k.get("sources")]
    unsourced += [k for k, v in SEBI_FACTS.items() if not v.get("source")]
    return Result(FAIL if unsourced else PASS,
                  f"{len(KNOWLEDGE)} principles and {len(SEBI_FACTS)} SEBI fact sets; {len(unsourced)} without a source",
                  {"unsourced": unsourced})
