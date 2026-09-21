"""Who holds what: index futures and options positioning by participant.

Derivatives are zero-sum before costs: every contract one participant is
long, another is short. So the retail ("Client") book is always the mirror
of the other three combined, and this is the most direct answer the public
data gives to "who is on the other side of my trade".

Described, not traded on. Whether FII positioning leads the market is a
hypothesis like any other; nothing here tests it or implies it.

What it cannot show: open interest is positions held at the close. Most
retail option buying is intraday — SEBI found about 59% of index-option
turnover in FY26 was in contracts expiring that same day — and never appears
here. So this data does not show retail losing to institutions; SEBI's
profit-and-loss studies do. It shows who carries risk overnight.
"""

import statistics

from storage.participant_oi_db import PARTICIPANTS, load


def _net(r: dict) -> dict:
    fl, fs = r.get("fut_idx_long", 0), r.get("fut_idx_short", 0)
    return {
        "index_futures_net": fl - fs,
        "index_futures_long_share": round(fl / (fl + fs), 3) if fl + fs else None,
        "index_calls_net": r.get("opt_idx_call_long", 0) - r.get("opt_idx_call_short", 0),
        "index_puts_net": r.get("opt_idx_put_long", 0) - r.get("opt_idx_put_short", 0),
        "index_options_bought": r.get("opt_idx_call_long", 0) + r.get("opt_idx_put_long", 0),
        "index_options_sold": r.get("opt_idx_call_short", 0) + r.get("opt_idx_put_short", 0),
    }


def by_day() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in load():
        out.setdefault(r["trade_date"], {})[r["participant"]] = r
    return {d: v for d, v in out.items() if set(v) == set(PARTICIPANTS)}


# Since mid-2021 NSE's option counts are rounded, so longs and shorts can
# differ by a contract out of millions. Anything larger means the file, or
# the parsing, is wrong.
ZERO_SUM_TOLERANCE = 2


def zero_sum_check(day: dict[str, dict]) -> dict:
    """Longs minus shorts across all participants, instrument by instrument —
    zero up to NSE's rounding. A data-integrity check on the file as much as
    a lesson: every contract held long is held short by someone."""
    gaps = {}
    for long_col, short_col in (("fut_idx_long", "fut_idx_short"), ("opt_idx_call_long", "opt_idx_call_short"),
                                ("opt_idx_put_long", "opt_idx_put_short")):
        L = sum(day[p].get(long_col, 0) for p in PARTICIPANTS)
        S = sum(day[p].get(short_col, 0) for p in PARTICIPANTS)
        gaps[long_col.replace("_long", "")] = int(L - S)
    return gaps


def latest() -> dict:
    days = by_day()
    if not days:
        return {"available": False, "reason": "no participant data yet — scripts/backfill_participant_oi.py"}
    dates = sorted(days)
    d, prev = dates[-1], (dates[-2] if len(dates) > 1 else None)
    year = dates[-250:]
    out = {}
    for p in PARTICIPANTS:
        now = _net(days[d][p])
        hist = [_net(days[x][p])["index_futures_long_share"] for x in year]
        hist = [h for h in hist if h is not None]
        out[p] = {
            **now,
            "index_futures_net_change": (now["index_futures_net"] - _net(days[prev][p])["index_futures_net"])
            if prev else None,
            "futures_long_share_percentile_1y": (round(100 * sum(h <= now["index_futures_long_share"] for h in hist)
                                                       / len(hist)) if hist and now["index_futures_long_share"]
                                                 is not None else None),
            "options_buyer_share": (round(now["index_options_bought"] / (now["index_options_bought"]
                                                                          + now["index_options_sold"]), 3)
                                    if now["index_options_bought"] + now["index_options_sold"] else None),
        }
    return {"available": True, "date": d, "previous": prev, "by_participant": out,
            "zero_sum_gaps": zero_sum_check(days[d]),
            "note": ("Contracts held at the close, from NSE's participant-wise open interest. Client is mostly "
                     "individuals; Pro is brokers trading their own money. Every long is someone else's short, so "
                     "these net to zero across the four. It shows who carries risk overnight — not the intraday "
                     "option buying that makes up most retail activity, which never reaches the close. "
                     "Description, not a signal.")}


def history_summary() -> dict:
    """How each participant has typically been positioned since 2019."""
    days = by_day()
    if not days:
        return {"available": False}
    out = {}
    for p in PARTICIPANTS:
        nets = [_net(v[p]) for v in days.values()]
        fut = [n["index_futures_net"] for n in nets]
        buyer = [n["index_options_bought"] / (n["index_options_bought"] + n["index_options_sold"])
                 for n in nets if n["index_options_bought"] + n["index_options_sold"]]
        out[p] = {
            "days_net_long_index_futures": round(sum(f > 0 for f in fut) / len(fut), 2),
            "median_options_buyer_share": round(statistics.median(buyer), 3) if buyer else None,
        }
    dates = sorted(days)
    return {"available": True, "days": len(dates), "period": f"{dates[0]} to {dates[-1]}", "by_participant": out,
            "note": ("Options buyer share: of each participant's index-option contracts, the share held long. "
                     "Above 0.5, they mostly buy options; below, they mostly sell them.")}
