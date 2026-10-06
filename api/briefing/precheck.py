"""Before you buy: one contract, checked against what is already measured.

For the call or put the reader is about to buy, and the moment they plan to
sell, from the live chain and the archive:

  charges   both legs at the rate card (₹20 an order, GST, STT on the sale,
            the exchange's and SEBI's fees, stamp duty), and the bid-ask
            spread: what selling straight away would return.
  waiting   what the contract is worth at the exit if NIFTY does not move:
            the decay, repriced on the market clock at its own implied
            volatility (options/move_table.py's model).
  break-even  the smallest NIFTY move, the contract's way, that gets back
            what was paid with both legs' charges and half the spread at
            the exit. Volatility held where it is; a fall in it costs more.
  history   how often NIFTY has moved that far, that way, over the same
            window since 2015: from the same time of day for windows inside
            a session (5-minute bars), from a close for windows of sessions
            (daily bars); at some point in the window, and still at its end.
            Kept as a share of price, counted at today's price.
  forecast  for a window ending in the session the day-ahead forecast is
            for, the break-even against its 68% range.

Each line is a measurement with the threshold that marks it written in it.
Nothing here says whether to buy: no rule has cleared the evidence bar, and
the decision stays with the reader.
"""

import bisect
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from backtest.options_engine import LOT_SIZE, OptionsCostModel
from briefing.journal import black76, implied_vol, intrinsic
from market_data.kite_session import IST
from options.move_table import years_to

SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
WINDOWS = {"15m": "15 minutes", "30m": "30 minutes", "60m": "an hour", "close": "the session's close",
           "1s": "the next session's close", "2s": "2 sessions' closes", "3s": "3 sessions' closes",
           "5s": "5 sessions' closes", "expiry": "expiry"}
CHARGES_WARN_PCT = 10.0     # charges both ways at a tenth of the premium or more
SPREAD_WARN_PCT = 5.0
FLAT_WARN_PCT = 25.0
HISTORY_WARN_PCT = 25.0     # still that far at the end of the window in fewer than one in four
MAX_MOVE_SHARE = 0.25       # a break-even beyond a 25% move is reported as out of reach


# --- when --------------------------------------------------------------------------------

def _next_session(d: date, holidays: set) -> date:
    from market_data.nse_holidays import sessions_after
    return sessions_after(d, 1, holidays)[0]


def exit_time(window: str, now: datetime, expiry: date, holidays: set) -> datetime:
    """The moment the reader plans to sell, never after the expiry's close."""
    from market_data.nse_holidays import is_session, sessions_after
    today = now.date()
    in_session = is_session(today, holidays) and SESSION_OPEN <= now.time() < SESSION_CLOSE
    before_open = is_session(today, holidays) and now.time() < SESSION_OPEN
    day = today if in_session or before_open else _next_session(today, holidays)
    close = datetime.combine(day, SESSION_CLOSE, tzinfo=IST)
    if window.endswith("m"):
        start = now if in_session else datetime.combine(day, SESSION_OPEN, tzinfo=IST)
        out = min(start + timedelta(minutes=int(window[:-1])), close)
    elif window == "close":
        out = close
    elif window.endswith("s"):
        out = datetime.combine(sessions_after(today, int(window[:-1]), holidays)[-1], SESSION_CLOSE, tzinfo=IST)
    elif window == "expiry":
        out = datetime.combine(expiry, SESSION_CLOSE, tzinfo=IST)
    else:
        raise ValueError(f"unknown window {window}")
    return min(out, datetime.combine(expiry, SESSION_CLOSE, tzinfo=IST))


# --- money -------------------------------------------------------------------------------

def economics(kind: str, strike: float, expiry: date, premium: float, bid: float | None, ask: float | None,
              lots: int, forward: float, now: datetime, exit_at: datetime, holidays: set,
              costs: OptionsCostModel, lot: int = LOT_SIZE) -> dict:
    q = lots * lot
    today, exit_day = now.date(), exit_at.date()
    mid = (bid + ask) / 2 if bid and ask else premium
    iv = implied_vol(mid, forward, strike, years_to(expiry, now, holidays), kind)
    left = years_to(expiry, exit_at, holidays)
    half_spread = (ask - bid) / 2 if bid and ask and ask >= bid else 0.0
    buy = costs.buy_cost_rs(premium, q, today)
    e = {"kind": kind, "strike": strike, "expiry": expiry.isoformat(), "premium": premium, "bid": bid, "ask": ask,
         "lots": lots, "quantity": q, "forward": round(forward, 2), "direction": "up" if kind == "CE" else "down",
         "iv": round(iv * 100, 2) if iv else None, "exit_at": exit_at.isoformat(timespec="minutes"),
         "years_left_at_exit": left, "half_spread": half_spread, "exit_day": exit_day.isoformat(),
         "checked_on": today.isoformat(),
         "paid_rs": round(premium * q + buy, 2), "buy_charges_rs": round(buy, 2),
         "charges_rs": round(buy + costs.sell_cost_rs(premium, q, today), 2),
         "spread_rs": round((ask - bid) * q, 2) if bid and ask else None,
         "spread_pct": round((ask - bid) / ask * 100, 2) if bid and ask else None}
    e["charges_pct"] = round(e["charges_rs"] / (premium * q) * 100, 2)
    e["sell_now_rs"] = round((bid * q - costs.sell_cost_rs(bid, q, today)) - e["paid_rs"], 2) if bid else None
    e["_costs"] = costs
    flat = net_at(e, 0.0)
    e["flat_rs"] = round(flat, 2)
    e["flat_pct"] = round(flat / e["paid_rs"] * 100, 1)
    e["value_flat"] = round(_value(e, forward), 2)
    hi = forward * MAX_MOVE_SHARE
    if net_at(e, hi) < 0:
        e["breakeven_pts"] = None
    elif flat >= 0:
        e["breakeven_pts"] = 0.0
    else:
        lo_m, hi_m = 0.0, hi
        for _ in range(60):
            m = (lo_m + hi_m) / 2
            lo_m, hi_m = (m, hi_m) if net_at(e, m) < 0 else (lo_m, m)
        e["breakeven_pts"] = round(hi_m, 1)
    return e


def _value(e: dict, level: float) -> float:
    left, iv = e["years_left_at_exit"], e["iv"]
    if left > 0 and iv:
        return black76(level, e["strike"], left, iv / 100, e["kind"])
    return intrinsic(e["kind"], e["strike"], level)


def net_at(e: dict, move_pts: float) -> float:
    """Rupees made or lost, after both legs' charges, if NIFTY has moved
    `move_pts` the contract's way by the exit and it is sold at the bid
    (the model's value less half the spread)."""
    d = 1 if e["kind"] == "CE" else -1
    sale = max(_value(e, e["forward"] + d * move_pts) - e["half_spread"], 0.0)
    fee = e["_costs"].sell_cost_rs(sale, e["quantity"], date.fromisoformat(e["exit_day"])) if sale > 0 else 0.0
    return sale * e["quantity"] - fee - e["paid_rs"]


# --- history -----------------------------------------------------------------------------

def intraday_moves(bars5: pd.DataFrame, start: datetime, minutes: int | None, direction: str) -> tuple[np.ndarray, np.ndarray]:
    """For every session in `bars5`: from the last 5-minute close at `start`'s
    time of day, over `minutes` (to the session's close when None), the
    furthest move `direction` (% of that close, by the bars' highs or lows) and
    where it stood at the end. Sessions without the whole window are left out."""
    slot = start.hour * 60 + start.minute
    first = max(slot - 5, 9 * 60 + 15)                      # the bar that closed at `start`, or the first
    first -= (first - (9 * 60 + 15)) % 5
    last_bar = 15 * 60 + 25
    touch, end = [], []
    d = 1 if direction == "up" else -1
    for _, s in bars5.groupby(bars5.index.date):
        mins = s.index.hour * 60 + s.index.minute
        i = np.flatnonzero(mins == first)
        if not len(i):
            continue
        i = int(i[0])
        stop_min = last_bar if minutes is None else min(first + minutes, last_bar)
        j = np.flatnonzero(mins == stop_min)
        if not len(j) or j[0] <= i:
            continue
        j = int(j[0])
        c0 = float(s["close"].iloc[i])
        win = s.iloc[i + 1:j + 1]
        far = (win["high"].max() - c0) if d > 0 else (c0 - win["low"].min())
        touch.append(far / c0 * 100)
        end.append((float(win["close"].iloc[-1]) - c0) * d / c0 * 100)
    return np.array(touch), np.array(end)


def session_moves(daily: pd.DataFrame, n: int, direction: str) -> tuple[np.ndarray, np.ndarray]:
    """From each close, over the next `n` sessions: the furthest move
    `direction` (% of that close) and where it stood at the n-th close."""
    c, h, lo = (daily[k].to_numpy(float) for k in ("close", "high", "low"))
    d = 1 if direction == "up" else -1
    touch, end = [], []
    for t in range(len(c) - n):
        w = slice(t + 1, t + 1 + n)
        far = (h[w].max() - c[t]) if d > 0 else (c[t] - lo[w].min())
        touch.append(far / c[t] * 100)
        end.append((c[t + n] - c[t]) * d / c[t] * 100)
    return np.array(touch), np.array(end)


def share(pct_moves: np.ndarray, move_pts: float, price: float) -> float | None:
    if not len(pct_moves):
        return None
    s = np.sort(pct_moves)
    need = move_pts / price * 100 - 1e-9
    return round((len(s) - bisect.bisect_left(s.tolist(), need)) / len(s) * 100, 1)


# --- in words ----------------------------------------------------------------------------

def _rs(v: float) -> str:
    return f"{'−' if v < 0 else ''}₹{abs(v):,.0f}"


def _pct(v: float) -> str:
    return f"{'−' if v < 0 else '+' if v > 0 else ''}{abs(v):.0f}%"


def _when(e: dict, window: str) -> str:
    at = datetime.fromisoformat(e["exit_at"])
    if at.date().isoformat() == e.get("checked_on"):
        return f"{at:%H:%M} today"
    return f"{at:%H:%M} on {at:%-d %b}" if window.endswith("m") else f"the {at:%-d %b} close"


def flags(e: dict, touch: float | None, end: float | None, forecast: dict | None, window: str, spot: float,
          sample: int | None = None, basis: str = "") -> list[dict]:
    """Each check as a sentence, 'warn' where it crosses the threshold the sentence names."""
    out = []
    when = _when(e, window)
    side = "up" if e["kind"] == "CE" else "down"
    pay = e["premium"] * e["quantity"]
    out.append({"key": "charges", "tone": "warn" if e["charges_pct"] >= CHARGES_WARN_PCT else "info",
                "text": f"Charges both ways come to {_rs(e['charges_rs'])}, {e['charges_pct']:.1f}% of the {_rs(pay)} "
                        f"you would pay (marked at {CHARGES_WARN_PCT:.0f}% or more). ₹20 an order weighs most on a cheap option."})
    if e["spread_pct"] is not None:
        out.append({"key": "spread", "tone": "warn" if e["spread_pct"] >= SPREAD_WARN_PCT else "info",
                    "text": f"The bid-ask spread is {e['spread_pct']:.1f}% of the price (marked at {SPREAD_WARN_PCT:.0f}%): "
                            f"selling straight away would come to {_rs(e['sell_now_rs'])} after charges."})
    out.append({"key": "flat", "tone": "warn" if -e["flat_pct"] >= FLAT_WARN_PCT else "info",
                "text": f"If NIFTY does not move, by {when} the contract is worth about ₹{e['value_flat']:,.2f} a unit: "
                        f"{_rs(e['flat_rs'])} ({_pct(e['flat_pct'])}) after charges and the spread (marked at a "
                        f"{FLAT_WARN_PCT:.0f}% loss). Volatility is held where it is; a fall in it costs more."})
    m = e["breakeven_pts"]
    if m is None:
        out.append({"key": "breakeven", "tone": "warn",
                    "text": f"No NIFTY move up to {MAX_MOVE_SHARE:.0%} gets the money back by {when}."})
    else:
        level = spot + (m if side == "up" else -m)
        text = (f"To get back what you paid by {when}, NIFTY needs to be about {m:,.0f} pts {side}, near {level:,.0f}.")
        tone = "info"
        if forecast and forecast.get("sigma_pts") and forecast.get("target_day") == e["exit_day"]:
            s = forecast["sigma_pts"]
            text += (f" The day-ahead forecast's 68% range for that session is ±{s:,.0f} pts from the previous close: "
                     f"this is {m / s:.1f}× that.")
            tone = "warn" if m > s else "info"
        out.append({"key": "breakeven", "tone": tone, "text": text})
    if m is not None and touch is not None and end is not None:
        out.append({"key": "history", "tone": "warn" if end < HISTORY_WARN_PCT else "info",
                    "text": f"Since 2015, {basis}NIFTY went {m:,.0f}+ pts {side} at some point in that time in {touch:.0f}% "
                            f"of cases, and was still that far {side} at the end in {end:.0f}%"
                            f"{f' of {sample:,}' if sample else ''} (marked under {HISTORY_WARN_PCT:.0f}%). "
                            f"The forecast and the history size the move; neither says which way."})
    if datetime.fromisoformat(e["exit_at"]).date().isoformat() == e["expiry"]:
        out.append({"key": "expiry", "tone": "info",
                    "text": f"This is expiry day for the contract: at 15:30 on {date.fromisoformat(e['expiry']):%-d %b} "
                            f"it is worth only what it is in the money."})
    return out


# --- live --------------------------------------------------------------------------------

def _history_frames() -> dict:
    from cache import cached

    def build():
        from market_data.bar_archive import ArchiveProvider
        from briefing.indicator_history import load
        candles = ArchiveProvider().get_ohlc("^NSEI", "5m", date(2015, 1, 1), date.today())
        idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
        idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
        bars5 = pd.DataFrame({k: [getattr(c, k) for c in candles] for k in ("open", "high", "low", "close")}, index=idx)
        daily, _, _ = load()
        return {"bars5": bars5, "daily": daily}
    return cached("precheck_history", ttl_seconds=3600, producer=build, stale_ok=True)


def _forecast() -> dict | None:
    try:
        from storage import day_forecast_db
        recs = day_forecast_db.records()
        if not recs:
            return None
        r = max(recs, key=lambda x: x["target_day"])
        return {"target_day": r["target_day"], "sigma_pts": r["forecast"].get("sigma_pts"),
                "band68": r["forecast"].get("band68")}
    except Exception:
        return None


def history_for(e: dict, window: str, now: datetime, holidays: set, frames: dict) -> dict:
    from market_data.nse_holidays import is_session
    m, side = e["breakeven_pts"], e["direction"]
    if m is None:
        return {"touch_pct": None, "end_pct": None, "n": 0, "basis": ""}
    in_session = is_session(now.date(), holidays) and SESSION_OPEN <= now.time() < SESSION_CLOSE
    if window.endswith("m") or window == "close":
        start = now if in_session else datetime.combine(now.date(), SESSION_OPEN, tzinfo=IST)
        minutes = None if window == "close" else int(window[:-1])
        touch, end = intraday_moves(frames["bars5"], start, minutes, side)
        basis = f"from {start:%H:%M} " if in_session else "from the first 5-minute close "
    else:
        n = sum(1 for k in range(1, 400)
                if (d := now.date() + timedelta(days=k)) <= date.fromisoformat(e["exit_day"]) and is_session(d, holidays))
        touch, end = session_moves(frames["daily"], max(n, 1), side)
        basis = f"over {max(n, 1)} session{'s' if n != 1 else ''} from a close, "
    return {"touch_pct": share(touch, m, e["forward"]), "end_pct": share(end, m, e["forward"]), "n": len(touch),
            "basis": basis}


def run_check(kind: str, strike: float, expiry_nse: str, lots: int = 1, premium: float | None = None,
              window: str = "close", now: datetime | None = None) -> dict:
    """The check for one contract from the live chain. `expiry_nse` as NSE
    writes it (13-Oct-2026)."""
    from market_data.nse_holidays import trading_holidays
    from options.chain_table import live_chain_table
    from options.move_table import forward_from
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {', '.join(WINDOWS)}")
    now = now or datetime.now(IST)
    holidays, _ = trading_holidays()
    chain = live_chain_table(expiry_nse, now.date())
    row = next((r for r in chain["rows"] if r["strike"] == float(strike)), None)
    c = row and row["call" if kind == "CE" else "put"]
    if not c:
        raise LookupError(f"NSE lists no {kind} at {strike:g} for {expiry_nse}")
    expiry = datetime.strptime(expiry_nse, "%d-%b-%Y").date()
    paid = premium or c.get("ask") or c.get("ltp")
    if not paid:
        raise LookupError(f"No price for the {strike:g} {kind}: enter what you would pay")
    atm = next(r for r in chain["rows"] if r["is_atm"])
    forward, forward_basis = forward_from(atm, chain["underlying_value"])
    exit_at = exit_time(window, now, expiry, holidays)
    e = economics(kind, float(strike), expiry, float(paid), c.get("bid"), c.get("ask"), lots, forward, now, exit_at,
                  holidays, OptionsCostModel(premium_slippage_pct=0.0), chain["lot_size"])
    try:
        hist = history_for(e, window, now, holidays, _history_frames())
    except Exception:
        hist = {"touch_pct": None, "end_pct": None, "n": 0, "basis": ""}
    fc = _forecast()
    checks = flags(e, hist["touch_pct"], hist["end_pct"], fc, window, chain["underlying_value"], hist["n"], hist["basis"])
    e.pop("_costs")
    return {"as_of": now.isoformat(timespec="seconds"), "chain_as_of": chain["as_of"], "spot": chain["underlying_value"],
            "forward_basis": forward_basis, "window": window, "window_label": WINDOWS[window],
            "price_source": "your price" if premium else ("the ask" if c.get("ask") else "the last trade"),
            "contract": e, "history": hist, "forecast": fc, "checks": checks,
            "marked": sum(1 for f in checks if f["tone"] == "warn"),
            "note": ("Measurements for one contract, not a verdict on it: no rule has cleared the evidence bar, so "
                     "nothing here says whether to buy. Charges are the rate card's; the spread and price are NSE's "
                     "chain; the value at the exit is modelled at the contract's own implied volatility, held still.")}
