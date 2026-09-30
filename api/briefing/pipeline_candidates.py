"""The strategy pipeline's two daily straddles as candidates for the Today
call, held to the same gate as the patterns.

  event_straddle      the close before a scheduled event
  cheap_vol_straddle  30-day implied volatility below the last 21 sessions' realised

Each is listed when its condition holds on the last close, with its study
verdict and why it does not qualify. A straddle is never the call itself:
the forward log records a call, a put or no trade, and is judged by
direction, so a straddle that ever cleared the bar would be said to, and the
call would stay NO_TRADE until the forward log can record one.
"""

from datetime import date, timedelta

from backtest.nifty_pipeline import BUDGETS, ELECTION_RESULTS, RBI_DECISIONS, RBI_OFF_CYCLE, RV_WINDOW, realised_vol

# RBI's schedule for the rest of 2026-27 (press release of 23 Mar 2026, "Meeting
# Schedule of the Monetary Policy Committee for 2026-2027"): meetings 5-7 Oct,
# 2-4 Dec, 3-5 Feb; the decision is announced on the last day, as the
# registered 8 Apr, 5 Jun and 5 Aug were. The 2027 Budget date is not yet
# announced and is added when it is.
UPCOMING_RBI = ("2026-10-07", "2026-12-04", "2027-02-05")


def events() -> dict[str, str]:
    off = set(RBI_OFF_CYCLE)
    out = {d: "RBI policy decision" for d in (*RBI_DECISIONS, *UPCOMING_RBI) if d not in off}
    out.update({d: "Union Budget" for d in BUDGETS})
    out.update({d: "general-election results" for d in ELECTION_RESULTS})
    return out


def next_weekday(day: date) -> date:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _evidence(study: dict | None, name: str) -> dict:
    for h in (study or {}).get("hypotheses", []):
        if h["name"] == name:
            hold = h.get("holdout") or {}
            return {"status": h["verdict"], "reason": h["reason"], "t": hold.get("t_vs_baseline"),
                    "n": hold.get("num_trades", 0), "mean_pct": hold.get("mean_pct")}
    return {"status": "REJECTED", "reason": "The pipeline's study has not been run.", "t": None, "n": 0,
            "mean_pct": None}


def _candidate(name: str, label: str, ev: dict, tests: int) -> dict:
    from stats.multiple_comparisons import required_t
    own_bar = required_t(tests, df=ev["n"] - 1) if ev["n"] >= 2 else None
    if ev["status"] != "APPROVED":
        why_not = f"option verdict {ev['status']}"
    elif ev["t"] is None or own_bar is None or ev["t"] < own_bar:
        why_not = f"APPROVED, but t {ev['t']} is below the {own_bar} bar for {ev['n']} holdout trades"
    else:
        why_not = ("clears the bar, but the forward log records only a call or a put; it must learn to record "
                   "a straddle before one can be the call")
    return {"strategy": name, "label": label, "direction": "straddle", "option_type": "CE+PE",
            "status": ev["status"], "verdict_reason": ev["reason"],
            "suggested_option": "the at-the-money call and put, the nearest expiry after the exit",
            "holdout_trades": ev["n"], "holdout_avg_profit_per_lot_rs": None, "holdout_mean_pct": ev["mean_pct"],
            "holdout_t_stat": ev["t"], "required_t": own_bar, "qualifies": False, "why_not": why_not}


def straddle_candidates(as_of: str, tests: int, closes: dict[date, float], iv_30d: float | None,
                        study: dict | None) -> list[dict]:
    """The straddles whose condition holds on the `as_of` close."""
    out = []
    day = date.fromisoformat(as_of)
    nxt = next_weekday(day).isoformat()
    what = events().get(nxt)
    if what:
        out.append(_candidate("event_straddle", f"Event straddle ({what} on {date.fromisoformat(nxt).day} {date.fromisoformat(nxt):%b})",
                              _evidence(study, "event_straddle"), tests))
    upto = [closes[d] for d in sorted(closes) if d <= day][-(RV_WINDOW + 1):]
    rv = realised_vol(upto)
    if iv_30d is not None and rv is not None and iv_30d < rv:
        out.append(_candidate("cheap_vol_straddle",
                              f"Cheap-volatility straddle (implied {iv_30d * 100:.1f}% below realised {rv * 100:.1f}%)",
                              _evidence(study, "cheap_vol_straddle"), tests))
    return out


def live_inputs(as_of: str) -> tuple[dict[date, float], float | None]:
    """NIFTY's daily closes to `as_of` and that close's 30-day implied volatility."""
    from market_data.bar_archive import ArchiveProvider
    from storage.sqlite_open import open_db
    from backtest.course_strategies import API_DIR
    day = date.fromisoformat(as_of)
    closes = {date.fromisoformat(c.timestamp[:10]): float(c.close)
              for c in ArchiveProvider().get_ohlc("^NSEI", "1d", day - timedelta(days=60), day)}
    conn = open_db(API_DIR / "data" / "iv.db")
    try:
        row = conn.execute("SELECT iv_30d FROM iv_daily WHERE trade_date = ?", (as_of,)).fetchone()
    finally:
        conn.close()
    return closes, (float(row[0]) if row and row[0] else None)
