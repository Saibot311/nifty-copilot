"""Which strategies today's market suits: Jev's reading of the conditions,
next to Python's own account of whether each strategy is actually forming.

Two questions, answered by two different things, shown side by side:

  Is it forming?   Python. Arithmetic on real prices: formed on the last
                   close, would form if the index closed now (live 15-minute
                   data), or within reach of its trigger. Nothing guessed.
  Does it fit?     Jev. Given the computed market picture — trend, momentum,
                   volatility — and a strategy's own premise, is today the
                   kind of market that premise was written for?

What Jev is not asked, and cannot see: whether a strategy makes money, where
the market goes next, or a strategy's record, verdict or trigger. Every
strategy here was rejected on 2024-26 data, and a fit is a description of
conditions, not evidence. Nothing in this module reaches the recommendation
or the paper book (a test reads their source to keep it so).

Jev is paid per call. One request judges the whole shortlist, a reading is
stored, and a new one is asked for only when the market picture has changed
and at least MIN_INTERVAL has passed — so at most every fifteen minutes in a
session, and not at all while the market is shut and nothing moves.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from copilot import jev
from market_data.live_quote import IST
from storage.sqlite_open import open_db

# Bump — never edit a question in place — if the wording below changes.
QUESTION_SET = "fit_v1"
DB_PATH = Path(__file__).parent.parent / "data" / "strategy_fit.db"
MIN_INTERVAL = timedelta(minutes=15)
MAX_JUDGED = 8          # the shortlist; one request covers it
NEAR_PCT = 1.0          # a trigger within 1% of the index is "within reach" (as the live tracker)
MIN_BASE_RATE = 0.05    # or it forms on at least 5% of days like this one

ORDER = {"forming now": 0, "formed": 1, "within reach": 2, "possible next close": 3}


# --- is it forming? (Python) -------------------------------------------------

def _pct_to(index_now: float, ranges: list) -> float | None:
    if not ranges or not index_now:
        return None
    if any(lo <= index_now <= hi for lo, hi in ranges):
        return 0.0
    return round(min(min(abs(index_now - lo), abs(index_now - hi)) for lo, hi in ranges) / index_now * 100, 2)


def shortlist(prox: dict, live_rows: list[dict], index_now: float) -> list[dict]:
    """The strategies worth asking about: forming now, formed on the last
    close, within 1% of a trigger, or forming on at least 5% of days like
    this. The rest are far from forming, and judging their fit would cost
    money to describe a strategy that is not on the table."""
    live_now = {r["strategy"] for r in live_rows if r.get("would_form_now")}
    out = []
    for p in prox.get("patterns", []):
        if p.get("formed_today") is None:  # read off the option chain, not simulable from price
            continue
        ranges = (p.get("trigger") or {}).get("close_ranges_level") or []
        pct = _pct_to(index_now, ranges)
        base = p.get("probability_next") or 0.0
        if p["strategy"] in live_now:
            status = "forming now"
        elif p.get("formed_today"):
            status = "formed"
        elif pct is not None and pct <= NEAR_PCT:
            status = "within reach"
        elif ranges and base >= MIN_BASE_RATE:
            status = "possible next close"
        else:
            continue
        out.append({"strategy": p["strategy"], "label": p["label"],
                    "side": "call" if p.get("option_type") == "CE" else "put", "status": status,
                    "pct_to_trigger": None if status in ("forming now", "formed") else pct,
                    "trigger_ranges": ranges, "base_rate": round(base, 3),
                    "forms_when": p.get("forms_when"), "why": p.get("why")})
    out.sort(key=lambda r: (ORDER[r["status"]], r["pct_to_trigger"] if r["pct_to_trigger"] is not None else 99,
                            -r["base_rate"]))
    return out[:MAX_JUDGED]


# --- does it fit? (Jev) --------------------------------------------------------

def jev_state(market: dict, rows: list[dict]) -> dict:
    """What Jev sees: the market picture and each strategy's premise. Not its
    record, its verdict, its trigger, or whether it is forming."""
    return {"market": market,
            "strategies": {r["strategy"]: {"name": r["label"],
                                           "side": "bullish: it buys a call" if r["side"] == "call"
                                           else "bearish: it buys a put",
                                           "premise": r["forms_when"], "idea": r["why"]} for r in rows}}


def questions(rows: list[dict]) -> dict:
    note = ("Judge only whether the conditions the strategy's premise and idea rely on — the trend, momentum and "
            "volatility they assume — are present in the market described. Do not judge whether its rule has been "
            "met today, whether it would pay, or where the index goes next. A reversal idea needs a move stretched "
            "far enough to reverse; a breakout or momentum idea needs a trend running in its own direction; an idea "
            "that assumes the opposite of the market described does not fit it.")
    criteria = {
        "true": {"meaning": "The market described has the conditions the idea relies on.",
                 "examples": ["A bearish breakdown idea in a market already trending down, below its moving averages",
                              "An oversold-bounce idea after a sharp fall, with RSI near 30",
                              "A bullish breakout idea in a rising market above its moving averages"]},
        "false": {"meaning": "The market described contradicts the idea, or has none of what it relies on.",
                  "examples": ["A bullish breakout idea in a steady downtrend",
                               "An oversold-bounce idea in a calm market where nothing is stretched",
                               "A trend-following idea in a flat, directionless market"]},
    }
    return {f"fit__{r['strategy']}": {
        "type": "noul",
        "instructions": {"question": f"The market in `market` is the kind of market the strategy in "
                                     f"`strategies.{r['strategy']}` was designed for.", "note": note},
        "criteria": criteria} for r in rows}


def judge(market: dict, rows: list[dict]) -> dict[str, float | None]:
    """One request for the whole shortlist. A missing answer is unjudged
    (None), never zero. Raises jev.JevUnavailable."""
    if not rows:
        return {}
    answers = jev.ask(jev_state(market, rows), questions(rows))
    out = {}
    for r in rows:
        a = answers.get(f"fit__{r['strategy']}") or {}
        out[r["strategy"]] = round(float(a["noul"]), 3) if a.get("noul") is not None else None
    return out


# --- the market picture (Python) --------------------------------------------

def _inputs() -> tuple[dict, dict, list[dict], float]:
    from backtest.iv_research import load_series
    from backtest.live_patterns import live_patterns, merge_live
    from backtest.pattern_options import load_research
    from backtest.pattern_proximity import pattern_proximity
    from backtest.strategies import load_daily_data
    from cache import cached
    from market_data.live_quote import live_index_quote
    from quant import build_analysis

    a = build_analysis()
    ind = a["indicators"]
    prox = cached("proximity:^NSEI", ttl_seconds=1800, producer=lambda: pattern_proximity("^NSEI"))
    live = cached("live_patterns", ttl_seconds=60, producer=live_patterns)
    live_rows = merge_live(live, prox, load_research()) if live.get("candle") else []
    level, change, where, vix = a["price"], a["change_pct"], f"the {a['as_of'][:10]} close", ind.get("india_vix")
    try:
        q = live_index_quote()
        vix = q.get("india_vix") or vix       # NSE's own figure; Yahoo's daily one lags
        if live.get("candle"):
            level, change, where = q["last"], q.get("change_pct"), f"live, {q.get('fetched_at', '')[11:16]} IST"
    except Exception:
        pass
    df, _ = load_daily_data("^NSEI", 400)
    closes = df["close"]
    iv = load_series().dropna(subset=["iv_30d"])
    market = {
        "index": {"level": round(level, 1), "change_today_pct": change, "as_of": where},
        "trend": {"classifier": a["regime"], "ema20": ind.get("ema_20"), "ema50": ind.get("ema_50"),
                  "return_20_sessions_pct": round((closes.iloc[-1] / closes.iloc[-21] - 1) * 100, 2),
                  "below_52_week_high_pct": round((1 - closes.iloc[-1] / closes.tail(252).max()) * 100, 2)},
        "momentum": {"rsi_14": ind.get("rsi_14"), "adx_14": ind.get("adx_14")},
        "volatility": {"atr_14_points": ind.get("atr_14"), "historical_volatility_20d_pct": ind.get("historical_volatility_pct"),
                       "india_vix": vix, "implied_vol_30d_percentile_of_past_year":
                           round(float(iv["iv_pct"].iloc[-1])) if len(iv) else None},
    }
    return market, prox, live_rows, level


def _evidence() -> dict[str, dict]:
    """Each strategy's actual 2024-26 record, from Python — shown beside the
    fit so a reading is never mistaken for a result."""
    try:
        from backtest.pattern_options import load_research
        return {p["strategy"]: {"status": p.get("status"), "t": p.get("holdout_t_stat"), "bar": p.get("required_t")}
                for p in (load_research() or {}).get("patterns", [])}
    except Exception:
        return {}


# --- a stored reading ----------------------------------------------------------

def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, taken_at TEXT NOT NULL, question_set TEXT NOT NULL,
        state_hash TEXT NOT NULL, state_json TEXT NOT NULL, fits_json TEXT NOT NULL)""")
    return conn


def _last() -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM readings WHERE question_set = ? ORDER BY id DESC LIMIT 1",
                           (QUESTION_SET,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _store(now: datetime, state_hash: str, state: dict, fits: dict) -> None:
    conn = _connect()
    try:
        conn.execute("INSERT INTO readings (taken_at, question_set, state_hash, state_json, fits_json) VALUES (?,?,?,?,?)",
                     (now.isoformat(timespec="seconds"), QUESTION_SET, state_hash, json.dumps(state), json.dumps(fits)))
        conn.commit()
    finally:
        conn.close()


def reading(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    market, prox, live_rows, index_now = _inputs()
    rows = shortlist(prox, live_rows, index_now)
    state = jev_state(market, rows)
    state_hash = hashlib.sha256(json.dumps({"q": QUESTION_SET, "s": state}, sort_keys=True).encode()).hexdigest()[:16]
    last = _last()
    last_at = datetime.fromisoformat(last["taken_at"]) if last else None
    fits: dict = {}
    judged_at, note = None, None
    if last and last["state_hash"] == state_hash:
        fits, judged_at = json.loads(last["fits_json"]), last["taken_at"]
    elif last and now - last_at < MIN_INTERVAL:
        # The market has moved since; the last reading stands until the next is due.
        fits, judged_at = json.loads(last["fits_json"]), last["taken_at"]
        note = f"read at {last_at:%H:%M} IST on an earlier picture; next reading after {last_at + MIN_INTERVAL:%H:%M}"
    elif jev.available() and rows:
        try:
            fits = judge(market, rows)
            judged_at = now.isoformat(timespec="seconds")
            _store(now, state_hash, state, fits)
        except jev.JevUnavailable as e:
            note = str(e)
    elif not jev.available():
        note = "no TYPESAFE_API_KEY — what is forming is shown, the fit is not judged"
    evidence = _evidence()
    out_rows = [{**r, "fit": fits.get(r["strategy"]), "evidence": evidence.get(r["strategy"])} for r in rows]
    out_rows.sort(key=lambda r: (ORDER[r["status"]], -(r["fit"] if r["fit"] is not None else -1)))
    return {
        "as_of": now.isoformat(timespec="seconds"), "judged": bool(judged_at and any(v is not None for v in fits.values())),
        "judged_at": judged_at, "note": note, "question_set": QUESTION_SET, "market": market, "rows": out_rows,
        "judged_by": "TypeSafe Jev — one typed yes/no judgment per strategy",
        "caveat": ("Fit is Jev's reading of whether today's conditions are the kind each strategy's premise was "
                   "written for. It is not evidence, not a forecast and not a recommendation: every strategy here "
                   "was rejected on 2024-26 data, and none of this reaches the Today tab's call or the paper book. "
                   "Whether a strategy is forming is Python's arithmetic on real prices."),
    }
