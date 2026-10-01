"""The Today tab's intraday section: the strategy pipeline's three intraday
rules followed through the session in progress, on NIFTY's 5-minute bars.

The rules are the ones pre-registered in backtest/nifty_pipeline.py, followed
bar by bar the way the study followed them; a test replays history through
this file and requires the study's own trades. Only completed bars count: a
bar still forming has no close, and every rule acts on closes.

What it shows is the rule, not advice. A rule whose study verdict is not
APPROVED is shown doing what it did today, with why that is not a trade;
"Consider" is written only for an APPROVED rule, and none is.
"""

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from backtest.course_strategies import Series
from backtest.nifty_pipeline import NOISE_LOOKBACK, NOISE_MIN_SESSIONS, PREREGISTERED, load_nifty_pipeline
from market_data.kite_session import IST

RULES = ("noise_band", "last_half_hour", "opening_range_5m")
BAR_MIN = 5
NOISE_FIRST, NOISE_LAST, NOISE_STEP = 9 * 60 + 45, 15 * 60 + 15, 30   # bar closes
FLAT = 15 * 60 + 25                                                   # the close of the bar stamped 15:20
HISTORY_DAYS = 40                                                     # calendar days: 14 sessions and more


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _end(s: Series, i: int) -> int:
    """The clock time bar i closes: a bar stamped 09:40 closes at 09:45."""
    return int(s.hm[i]) + BAR_MIN


def _is_check(end: int) -> bool:
    return NOISE_FIRST <= end <= NOISE_LAST and (end - NOISE_FIRST) % NOISE_STEP == 0


def _prev_close(s: Series, daily_close: dict, k: int, day: date) -> float | None:
    """The previous session's official close. From the daily archive, which
    has every session even when a day's 5-minute bars are missing: taking
    "the session before in the bars" then would reach back a day (Kite stopped
    serving 30 Sep's 5-minute bars at midnight, 1 Oct 2026). Without daily
    closes, the last bar of the session before."""
    earlier = [d for d in daily_close if d < day]
    if earlier:
        return daily_close[max(earlier)]
    if k == 0:
        return None
    return float(s.c[s.bounds[s.sessions[k - 1]][1]])


def missing_sessions(s: Series, daily_close: dict, day: date, n: int) -> list[date]:
    """The last `n` sessions before `day` that the daily archive has and the bars do not."""
    return [d for d in sorted(d for d in daily_close if d < day)[-n:] if d not in s.bounds]


def _at_ts(s: Series, i: int) -> str:
    return s.ts[i].isoformat()


# --- the three rules, on the bars so far -------------------------------------------

def noise_band_now(s: Series, daily_close: dict, day: date) -> dict:
    k = s.sessions.index(day)
    gaps = missing_sessions(s, daily_close, day, NOISE_LOOKBACK)
    if gaps:
        return {"status": "no_history", "missing": [d.isoformat() for d in gaps]}
    if k < NOISE_LOOKBACK:
        return {"status": "no_history"}
    prior = s.sessions[k - NOISE_LOOKBACK:k]
    moves = {}
    for p in prior:
        b0, b1 = s.bounds[p]
        moves[p] = {int(s.hm[i]): abs(s.c[i] / s.o[b0] - 1) for i in range(b0, b1 + 1)}

    def band(stamp: int) -> float | None:
        vals = [moves[p][stamp] for p in prior if stamp in moves[p]]
        return sum(vals) / len(vals) if len(vals) >= NOISE_MIN_SESSIONS else None

    b0, b1 = s.bounds[day]
    pc = _prev_close(s, daily_close, k, day)
    hi_ref, lo_ref = max(s.o[b0], pc), min(s.o[b0], pc)

    def levels(end: int) -> dict | None:
        sig = band(end - BAR_MIN)
        return None if sig is None else {"at": _hhmm(end), "upper": round(hi_ref * (1 + sig), 2),
                                        "lower": round(lo_ref * (1 - sig), 2)}

    entry = None
    for i in range(b0, b1 + 1):
        end = _end(s, i)
        if entry is None:
            if not _is_check(end):
                continue
            lv = levels(end)
            if lv is None:
                continue
            side = 1 if s.c[i] > lv["upper"] else -1 if s.c[i] < lv["lower"] else 0
            if side:
                entry = {"i": i, "side": side, "levels": lv}
            continue
        if end >= FLAT:
            return _closed(s, entry, i, "time")
        if not _is_check(end):
            continue
        sig = band(int(s.hm[i]))
        if sig is not None and (s.c[i] < hi_ref * (1 + sig) if entry["side"] > 0 else s.c[i] > lo_ref * (1 - sig)):
            return _closed(s, entry, i, "back inside")

    last_end = _end(s, b1)
    upcoming = [e for e in range(NOISE_FIRST, NOISE_LAST + 1, NOISE_STEP) if e > last_end]
    nxt = levels(upcoming[0]) if upcoming else None
    if entry:
        return {"status": "in_trade", "side": entry["side"], "entry_at": _at_ts(s, entry["i"]),
                "entry_index": round(float(s.c[entry["i"]]), 2), "entry_levels": entry["levels"], "next": nxt}
    if not upcoming:
        return {"status": "no_trade", "next": None}
    return {"status": "waiting", "next": nxt, "reference": {"open": round(float(s.o[b0]), 2),
                                                             "previous_close": round(float(pc), 2)}}


def last_half_hour_now(s: Series, daily_close: dict, day: date) -> dict:
    k = s.sessions.index(day)
    pc = _prev_close(s, daily_close, k, day)
    b0, b1 = s.bounds[day]
    at = {int(s.hm[i]): i for i in range(b0, b1 + 1)}
    i45, i_in, i_out = at.get(9 * 60 + 40), at.get(14 * 60 + 55), at.get(15 * 60 + 20)
    if pc is None:
        return {"status": "no_history"}
    if i45 is None:
        return {"status": "waiting", "next": {"at": "09:45"}}
    r = s.c[i45] / pc - 1
    first = {"first_half_hour_pts": round(float(s.c[i45] - pc), 2), "first_half_hour_pct": round(r * 100, 3),
             "previous_close": round(float(pc), 2)}
    if r == 0:
        return {"status": "no_trade", **first}
    side = 1 if r > 0 else -1
    base = {"side": side, **first}
    if i_in is None:
        return {**base, "status": "waiting", "next": {"at": "15:00"}}
    entry = {"entry_at": _at_ts(s, i_in), "entry_index": round(float(s.c[i_in]), 2)}
    if i_out is None:
        return {**base, **entry, "status": "in_trade", "next": {"at": "15:25"}}
    return {**base, **entry, "status": "closed", "exit_at": _at_ts(s, i_out), "exit_index": round(float(s.c[i_out]), 2),
            "exit_reason": "time"}


def opening_range_now(s: Series, daily_close: dict, day: date) -> dict:
    b0, b1 = s.bounds[day]
    if s.hm[b0] != 9 * 60 + 15:
        return {"status": "no_trade"}
    if s.c[b0] == s.o[b0]:
        return {"status": "no_trade", "first_candle": _candle(s, b0)}
    side = 1 if s.c[b0] > s.o[b0] else -1
    stop = float(s.l[b0] if side > 0 else s.h[b0])
    base = {"side": side, "first_candle": _candle(s, b0), "stop": round(stop, 2),
            "entry_at": _at_ts(s, b0), "entry_index": round(float(s.c[b0]), 2)}
    for j in range(b0 + 1, b1 + 1):
        if side > 0 and (s.o[j] <= stop or s.l[j] <= stop):
            return {**base, "status": "closed", "exit_at": _at_ts(s, j),
                    "exit_index": round(float(s.o[j] if s.o[j] <= stop else stop), 2), "exit_reason": "stop"}
        if side < 0 and (s.o[j] >= stop or s.h[j] >= stop):
            return {**base, "status": "closed", "exit_at": _at_ts(s, j),
                    "exit_index": round(float(s.o[j] if s.o[j] >= stop else stop), 2), "exit_reason": "stop"}
        if s.hm[j] == 15 * 60 + 20:
            return {**base, "status": "closed", "exit_at": _at_ts(s, j), "exit_index": round(float(s.c[j]), 2),
                    "exit_reason": "time"}
    return {**base, "status": "in_trade", "next": {"at": "15:25"}}


def _candle(s: Series, i: int) -> dict:
    return {"open": round(float(s.o[i]), 2), "high": round(float(s.h[i]), 2), "low": round(float(s.l[i]), 2),
            "close": round(float(s.c[i]), 2)}


def _closed(s: Series, entry: dict, j: int, reason: str) -> dict:
    return {"status": "closed", "side": entry["side"], "entry_at": _at_ts(s, entry["i"]),
            "entry_index": round(float(s.c[entry["i"]]), 2), "entry_levels": entry["levels"],
            "exit_at": _at_ts(s, j), "exit_index": round(float(s.c[j]), 2), "exit_reason": reason}


FOLLOW = {"noise_band": noise_band_now, "last_half_hour": last_half_hour_now, "opening_range_5m": opening_range_now}


# --- the contract, and the words ------------------------------------------------------

def contract(side: int, index_level: float, day: date, expiries: list[date]) -> dict | None:
    """The instrument the study priced (Phase 1's rule): the nearest expiry that
    does not expire that day, at the money (the study's rounding)."""
    later = sorted(e for e in expiries if e > day)
    if not later:
        return None
    return {"expiry": later[0].isoformat(), "strike": round(index_level / 50) * 50,
            "option_type": "CE" if side > 0 else "PE"}


def _describe(c: dict) -> str:
    return f"NIFTY {date.fromisoformat(c['expiry']):%d %b} {c['strike']:,} {c['option_type']}"


def line(label: str, st: dict, verdict: dict | None) -> str:
    """The sentence under a rule. Written here, not in the browser (I2), and
    "Consider" only for a rule whose study verdict is APPROVED."""
    status = st["status"]
    approved = (verdict or {}).get("verdict") == "APPROVED"
    what = {1: "call", -1: "put"}.get(st.get("side"))
    if verdict is None:
        held_back = " The study has not been run, so this is not a trade."
    elif approved:
        held_back = ""
    else:
        held_back = (f" Its evidence did not clear the bar (holdout t {verdict.get('holdout_t')} against "
                     f"{verdict.get('required_t')}), so this is not a trade.")
    if status == "no_history":
        if st.get("missing"):
            days = ", ".join(f"{date.fromisoformat(d).day} {date.fromisoformat(d):%b}" for d in st["missing"])
            return f"{label}: the 5-minute bars for {days} are missing, so its levels cannot be set."
        return f"{label}: not enough sessions in the archive to set its levels."
    if status == "in_trade" and approved and st.get("contract"):
        return f"Consider buying {_describe(st['contract'])} — {label}, holdout t {verdict.get('holdout_t')}."
    if status in ("in_trade", "closed"):
        done = f"; out at {st['exit_time']} ({st['exit_reason']})" if status == "closed" else ""
        if approved:
            return f"{label} bought the {what} at {st['entry_time']}{done}."
        return f"No intraday trade: {label} triggered at {st['entry_time']} on the {what} side{done}.{held_back}"
    if status == "no_trade":
        return f"{label}: no trigger today."
    return f"{label}: waiting for the {(st.get('next') or {}).get('at')} close.{held_back}"


def verdicts() -> dict:
    study = load_nifty_pipeline() or {}
    out = {}
    for h in study.get("hypotheses", []):
        hold = h.get("holdout") or {}
        out[h["name"]] = {"verdict": h["verdict"], "required_t": h.get("required_t"),
                          "holdout_t": hold.get("t_vs_baseline"), "holdout_mean_pct": hold.get("mean_pct"),
                          "holdout_baseline_pct": hold.get("baseline_mean_pct"), "holdout_trades": hold.get("num_trades")}
    return out


# --- the data ------------------------------------------------------------------------

def _frame(candles, now: datetime) -> pd.DataFrame:
    """Completed bars only: one still forming has no close yet."""
    if not candles:
        # Time-indexed even when empty: there is nothing newer than the archive
        # every evening after the nightly top-up, and on weekends; a plain
        # empty frame broke every caller that reads its dates (1 Oct 2026).
        return pd.DataFrame(columns=["open", "high", "low", "close"], index=pd.DatetimeIndex([], tz=IST), dtype=float)
    idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
    idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    df = pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                       "low": [c.low for c in candles], "close": [c.close for c in candles]}, index=idx)
    done = np.array([ts + timedelta(minutes=BAR_MIN) <= now for ts in df.index], dtype=bool)
    return df[done]


def five_minute_bars(now: datetime, closes: dict | None = None) -> tuple[pd.DataFrame, str | None]:
    """The archive's 5-minute bars (Kite, topped up nightly), then Kite's own
    for any day after it — Yahoo's when the Kite login has lapsed, and for any
    session in `closes` (the daily archive) Kite did not serve: it stops
    serving the day just gone at midnight until its end-of-day run."""
    from market_data.bar_archive import ArchiveProvider
    today = now.date()
    archived = _frame(ArchiveProvider().get_ohlc("^NSEI", "5m", today - timedelta(days=HISTORY_DAYS), today), now)
    since = archived.index[-1].date() + timedelta(days=1) if not archived.empty else today - timedelta(days=HISTORY_DAYS)
    source, recent = None, archived.iloc[:0]
    if since <= today:                                  # else the archive already has today
        try:
            from market_data.zerodha_provider import ZerodhaProvider
            recent, source = _frame(ZerodhaProvider().get_ohlc("^NSEI", "5m", since, today, now=now), now), "Kite"
        except Exception:
            try:
                from market_data.yfinance_provider import YFinanceProvider
                recent = _frame(YFinanceProvider().get_ohlc("^NSEI", "5m", since, today + timedelta(days=1)), now)
                source = "Yahoo"
            except Exception:
                recent = archived.iloc[:0]
    if not archived.empty:
        recent = recent[recent.index.normalize() > archived.index[-1].normalize()]
    have = set(recent.index.date) | set(archived.index.date)
    gaps = sorted(d for d in (closes or {}) if since <= d < today and d not in have)
    if gaps and source == "Kite":
        try:
            from market_data.yfinance_provider import YFinanceProvider
            filled = _frame(YFinanceProvider().get_ohlc("^NSEI", "5m", gaps[0], gaps[-1] + timedelta(days=1)), now)
            filled = filled[np.isin(filled.index.date, gaps)]
            if not filled.empty:
                recent = pd.concat([recent, filled])
                source = "Kite, and Yahoo for " + ", ".join(f"{d.day} {d:%b}" for d in sorted(set(filled.index.date)))
        except Exception:
            pass
    out = pd.concat([archived, recent]).sort_index()
    return out[~out.index.duplicated()], (source if not recent.empty else None)


def daily_closes(today: date) -> dict:
    from market_data.bar_archive import ArchiveProvider
    return {date.fromisoformat(c.timestamp[:10]): float(c.close)
            for c in ArchiveProvider().get_ohlc("^NSEI", "1d", today - timedelta(days=HISTORY_DAYS * 2), today)}


def expiries(today: date) -> list[date]:
    """NIFTY's listed expiries: Kite's instrument list, NSE's chain, then the
    options archive (enough for any past session)."""
    try:
        from market_data.kite_quotes import _instrument_map
        out = sorted({date.fromisoformat(k[1]) for k in _instrument_map() if k[0] == "NIFTY"})
        if out:
            return out
    except Exception:
        pass
    try:
        from market_data.live_quote import _session
        info = _session().option_chain_contract_info("NIFTY") or {}
        out = sorted(datetime.strptime(e, "%d-%b-%Y").date() for e in info.get("expiryDates") or [])
        if out:
            return out
    except Exception:
        pass
    from backtest.course_strategies import load_expiries
    return load_expiries()


def evaluate(bars: pd.DataFrame, closes: dict, listed: list[date], day: date | None = None) -> dict:
    """Every rule's state on `day` (the last session in `bars` by default)."""
    s = Series(bars)
    if not s.sessions:
        return {"session": None, "rules": []}
    day = day or s.sessions[-1]
    found = verdicts()
    rules = []
    for name in RULES:
        st = FOLLOW[name](s, closes, day)
        for k in ("entry", "exit"):
            if st.get(f"{k}_at"):
                stamp = pd.Timestamp(st[f"{k}_at"])
                st[f"{k}_time"] = _hhmm(stamp.hour * 60 + stamp.minute + BAR_MIN)
        if st.get("entry_index") is not None:
            st["contract"] = contract(st["side"], st["entry_index"], day, listed)
        label = PREREGISTERED["hypotheses"][name]["label"]
        rules.append({"name": name, "label": label, **st, "evidence": found.get(name),
                      "line": line(label, st, found.get(name))})
    b1 = s.bounds[day][1]
    # A session the daily archive has after the last one in the bars: that
    # day's 5-minute bars are missing, and what is shown is the day before.
    later = sorted(d for d in closes if d > day)
    return {"session": day.isoformat(), "bars_through": _hhmm(_end(s, b1)), "rules": rules,
            "missing_after": [d.isoformat() for d in later]}


def build_intraday(now: datetime | None = None) -> dict:
    from storage import intraday_forward_db as fwd
    now = now or datetime.now(IST)
    closes = daily_closes(now.date())
    bars, source = five_minute_bars(now, closes)
    out = evaluate(bars, closes, expiries(now.date()))
    try:
        record = fwd.summary()
        today = fwd.events(out["session"]) if out.get("session") else []
    except Exception:
        record, today = {}, []
    for r in out["rules"]:
        r["forward"] = record.get(r["name"])
        r["recorded_today"] = [{k: e[k] for k in ("kind", "bar_close_at", "price_at", "bid", "ask", "ltp")}
                               for e in today if e["rule"] == r["name"]]
    return {**out, "as_of": now.isoformat(timespec="seconds"), "source": source or "the archive",
            "note": ("The three intraday rules from the strategy pipeline, followed on completed 5-minute bars. "
                     "Their verdicts come from a modelled option on 2018-26. \"At real prices\" is each rule against "
                     "real option prices from 1 Oct 2026, bought at the ask and sold at the bid, counted when both "
                     "were taken within six minutes of the rule's bar.")}


def tick_contracts(state: dict | None) -> list[dict]:
    """The contracts a rule bought today, for the tick's one Kite call."""
    out = []
    for r in (state or {}).get("rules", []):
        c = r.get("contract")
        if c and r.get("status") in ("in_trade", "closed"):
            out.append({"id": f"i{r['name']}", "underlying": "NIFTY", **c})
    return out


# --- the forward record ---------------------------------------------------------------

def state_now(now: datetime) -> dict:
    closes = daily_closes(now.date())
    bars, source = five_minute_bars(now, closes)
    return {**evaluate(bars, closes, expiries(now.date())), "source": source}


def record(now: datetime, chain_rows: list[dict], state: dict | None = None,
           db_path=None) -> tuple[list[str], set[str]]:
    """Writes each rule's entry, then its exit, the first time a run sees them
    today, priced from the option chain saved in the same run. Returns what it
    wrote and the expiries whose chain was stamped before the rule's bar
    closed: NSE's chain runs a minute or two behind, and a price from before
    the signal existed is not one the rule could have paid (the first entry,
    1 Oct 2026, was priced 75 seconds early). Those wait for a fresher chain.
    Nothing is written without a price; a price taken well after the bar is
    kept but not counted (intraday_forward_db.ON_TIME_S)."""
    from storage import intraday_forward_db as fwd
    if state is None:
        state = state_now(now)
    if state.get("session") != now.date().isoformat():
        return [], set()
    prices = {(r["expiry"], float(r["strike"]), r["option_type"]): r for r in chain_rows}
    have = {(e["rule"], e["kind"]) for e in fwd.events(state["session"], db_path)}
    written, waiting = [], set()
    for r in state["rules"]:
        c = r.get("contract")
        if r["status"] not in ("in_trade", "closed") or not c:
            continue
        q = prices.get((c["expiry"], float(c["strike"]), c["option_type"]))
        if q is None:
            continue
        for kind in ("entry", "exit"):
            if (r["name"], kind) in have or (kind == "exit" and r["status"] != "closed"):
                continue
            if kind == "exit" and (r["name"], "entry") not in have and f"{r['name']} entry" not in written:
                continue                                # an exit is only worth having against an entry
            stamp = pd.Timestamp(r[f"{kind}_at"]) + timedelta(minutes=BAR_MIN)
            if (q.get("taken_at") or "")[:19] < stamp.isoformat()[:19]:
                waiting.add(c["expiry"])
                break                                   # the exit waits for its entry
            event = {"trade_day": state["session"], "rule": r["name"], "kind": kind, "side": r["side"],
                     "bar_close_at": stamp.isoformat(), "index_level": r[f"{kind}_index"],
                     "reason": r.get("exit_reason") if kind == "exit" else None, **c,
                     "price_at": q.get("taken_at"), "bid": q.get("bid"), "ask": q.get("ask"), "ltp": q.get("ltp"),
                     "recorded_at": now.isoformat(timespec="seconds"), "bars_source": state.get("source")}
            if fwd.record(event, db_path):
                written.append(f"{r['name']} {kind}")
    return written, waiting
