"""Kronos, an open-source foundation model for candlesticks (github.com/
shiyu-coder/Kronos, MIT, AAAI 2026), forecasting NIFTY beside the app's own
forecast, on the owner's request (10 Oct 2026).

Kronos runs in its own environment outside this app (KRONOS_DIR, by default
~/Documents/kronos: the official repo in repo/, a venv in .venv/, and
runner/run_kronos.py). This file builds its inputs from the app's archive,
calls it as a separate process, turns its sampled paths into bands, and keeps
the score:

  daily  the next session's close, from the last 400 daily candles, written
         before the session opens (nightly) and scored after.
  live   the next hour of five-minute candles, from the last 512 completed
         ones, every 15 minutes in the session; scored when the hour is over.

PATHS sampled futures give the bands: the middle 68% (16th to 84th
percentile) and 95% (2.5th to 97.5th), and the median path. The median's
side of the last close is Kronos's direction.

The past check (`hindcast`) runs the daily forecast over 2024 on and sets it
beside the app's own forecast on the same days. Kronos was trained on 12
billion candles from 45+ exchanges, very likely including NIFTY through 2024
or 2025, so its past check may be scored on prices it has seen; the card says
so. Only the forward record is a clean test.

NIFTY has no volume; the model is given zeros, which it was not trained on
for most markets. Nothing here is a reason to trade.
"""

import json
import os
import statistics
import subprocess
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np

from market_data.kite_session import IST

KRONOS_DIR = Path(os.environ.get("KRONOS_DIR", Path.home() / "Documents" / "kronos"))
PATHS = 40
DAILY_LOOKBACK, LIVE_LOOKBACK = 400, 512
LIVE_STEPS = 12                                   # an hour of five-minute candles
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
HINDCAST_FROM = date(2024, 1, 1)
API_DIR = Path(__file__).parent.parent
HINDCAST_PATH = API_DIR / "data" / "kronos_hindcast.json"


def available() -> bool:
    return (KRONOS_DIR / ".venv" / "bin" / "python").exists() and (KRONOS_DIR / "runner" / "run_kronos.py").exists()


def run(candles: list[dict], jobs: list[dict], lookback: int, paths: int = PATHS, timeout: int = 3600) -> dict:
    """Kronos over `jobs` (each: id, end index, future timestamps), in its own process."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        src.write_text(json.dumps({"candles": candles, "jobs": jobs, "lookback": lookback, "paths": paths}))
        subprocess.run([str(KRONOS_DIR / ".venv" / "bin" / "python"), "-I", str(KRONOS_DIR / "runner" / "run_kronos.py"),
                        str(src), str(dst)], check=True, timeout=timeout, capture_output=True)
        return json.loads(dst.read_text())


def bands(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    q = lambda p: round(float(np.percentile(a, p)), 2)  # noqa: E731
    return {"median": q(50), "p16": q(16), "p84": q(84), "p2_5": q(2.5), "p97_5": q(97.5)}


def summarise(result: dict, last_close: float) -> dict:
    """Bands at every step of the sampled close paths, and the direction."""
    closes = result["closes"]
    steps = [bands([p[k] for p in closes]) for k in range(len(closes[0]))]
    end = steps[-1]
    return {"last_close": round(last_close, 2), "steps": steps, "median": end["median"],
            "band68": [end["p16"], end["p84"]], "band95": [end["p2_5"], end["p97_5"]],
            "direction": "up" if end["median"] > last_close else "down",
            "median_move": round(end["median"] - last_close, 1), "paths": len(closes)}


def score(fc: dict, actual: float) -> dict:
    return {"close": round(actual, 2), "move": round(actual - fc["last_close"], 1),
            "inside68": fc["band68"][0] <= actual <= fc["band68"][1],
            "inside95": fc["band95"][0] <= actual <= fc["band95"][1],
            "direction_hit": (actual > fc["last_close"]) == (fc["direction"] == "up"),
            "error": round(actual - fc["median"], 1)}


# --- data -----------------------------------------------------------------------------

def _daily_candles(upto: date) -> list[dict]:
    from market_data.bar_archive import ArchiveProvider
    rows = ArchiveProvider().get_ohlc("^NSEI", "1d", date(2015, 1, 1), upto)
    return [{"t": f"{c.timestamp[:10]}T15:30:00+05:30", "open": c.open, "high": c.high, "low": c.low,
             "close": c.close, "volume": 0.0} for c in rows]


def _session_close(d: date) -> str:
    return datetime.combine(d, SESSION_CLOSE, tzinfo=IST).isoformat()


# --- daily -------------------------------------------------------------------------------

def run_daily(now: datetime | None = None, db_path=None, holidays: set | None = None) -> dict:
    """Score daily forecasts whose session has closed; forecast the next session if it has not opened."""
    from market_data.nse_holidays import sessions_after, trading_holidays
    from storage import kronos_db as db
    now = now or datetime.now(IST)
    if holidays is None:
        holidays, _ = trading_holidays()
    candles = _daily_candles(now.date())
    closes = {c["t"][:10]: c["close"] for c in candles}
    written = {"scored": [], "forecast": None}
    for rec in db.records("daily", db_path):
        if rec["outcome"] is None and rec["target"] in closes:
            db.add_outcome("daily", rec["target"], now.isoformat(timespec="seconds"),
                           score(rec["forecast"], closes[rec["target"]]), db_path)
            written["scored"].append(rec["target"])
    last = date.fromisoformat(candles[-1]["t"][:10])
    target = sessions_after(last, 1, holidays)[0]
    have = {r["target"] for r in db.records("daily", db_path)}
    if now < datetime.combine(target, SESSION_OPEN, tzinfo=IST) and target.isoformat() not in have and available():
        res = run(candles, [{"id": "next", "end": len(candles) - 1, "future": [_session_close(target)]}], DAILY_LOOKBACK)
        fc = {**summarise(res["results"]["next"], candles[-1]["close"]), "last_session": last.isoformat(),
              "target": target.isoformat(), "model": res["model"], "seconds": res["seconds"]}
        if db.add_forecast("daily", target.isoformat(), now.isoformat(timespec="seconds"), fc, db_path):
            written["forecast"] = target.isoformat()
    return written


# --- live ------------------------------------------------------------------------------------

def next_slots(last_start: datetime, n: int = LIVE_STEPS) -> list[datetime]:
    """The next `n` five-minute bars after `last_start` inside its session (start times)."""
    out, t = [], last_start
    close_at = datetime.combine(last_start.date(), SESSION_CLOSE, tzinfo=last_start.tzinfo)
    while len(out) < n:
        t += timedelta(minutes=5)
        if t + timedelta(minutes=5) > close_at:
            break
        out.append(t)
    return out


def run_live(now: datetime | None = None, db_path=None, bars=None) -> dict:
    """Score live forecasts whose hour has passed; in the session, forecast the next hour."""
    from briefing.intraday_live import daily_closes, five_minute_bars
    from storage import kronos_db as db
    now = now or datetime.now(IST)
    if bars is None:
        bars, _src = five_minute_bars(now, daily_closes(now.date()))
    written = {"scored": [], "forecast": None}
    by_start = {ts.to_pydatetime(): float(c) for ts, c in bars["close"].items()}
    for rec in db.records("live", db_path):
        last_start = datetime.fromisoformat(rec["forecast"]["target_bar"])
        if rec["outcome"] is None and last_start in by_start:
            db.add_outcome("live", rec["target"], now.isoformat(timespec="seconds"),
                           score(rec["forecast"], by_start[last_start]), db_path)
            written["scored"].append(rec["target"])
    if bars.empty or not available():
        return written
    last = bars.index[-1].to_pydatetime()
    in_session = now.weekday() < 5 and time(9, 30) <= now.time() <= time(15, 15) and last.date() == now.date()
    slots = next_slots(last) if in_session else []
    if len(slots) < 3:
        return written
    candles = [{"t": ts.isoformat(), "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                "close": float(r["close"]), "volume": 0.0} for ts, r in bars.tail(LIVE_LOOKBACK).iterrows()]
    res = run(candles, [{"id": "next", "end": len(candles) - 1, "future": [s.isoformat() for s in slots]}],
              LIVE_LOOKBACK, timeout=600)
    target = (slots[-1] + timedelta(minutes=5)).isoformat()
    fc = {**summarise(res["results"]["next"], candles[-1]["close"]), "from_bar_close": (last + timedelta(minutes=5)).isoformat(),
          "target_bar": slots[-1].isoformat(), "target": target, "slots": [s.isoformat() for s in slots],
          "model": res["model"], "seconds": res["seconds"]}
    if db.add_forecast("live", target, now.isoformat(timespec="seconds"), fc, db_path):
        written["forecast"] = target
    return written


# --- the past check, beside the app's own forecast --------------------------------------------

def run_hindcast(path: Path = HINDCAST_PATH) -> dict:
    """Kronos's daily forecast for every session from 2024 on, each from the
    candles before it, scored; and the app's own forecast on the same days."""
    import math

    from briefing.day_forecast import DEV_END, K_BOUNDS, Z68, Z95, _clip, history, load_inputs
    candles = _daily_candles(datetime.now(IST).date())
    idx = [i for i, c in enumerate(candles) if c["t"][:10] >= HINDCAST_FROM.isoformat() and i >= DAILY_LOOKBACK]
    jobs = [{"id": candles[i]["t"][:10], "end": i - 1, "future": [candles[i]["t"]]} for i in idx]
    res = run(candles, jobs, DAILY_LOOKBACK, timeout=6 * 3600)
    rows = []
    for i in idx:
        d = candles[i]["t"][:10]
        fc = summarise(res["results"][d], candles[i - 1]["close"])
        rows.append({"day": d, **score(fc, candles[i]["close"]), "band68": fc["band68"], "band95": fc["band95"],
                     "median": fc["median"], "direction": fc["direction"]})
    inp = load_inputs(datetime.now(IST).date())
    ours_rows = history(inp["daily"], inp["iv30"], inp["events"], inp["expiries"])
    dev = [r for r in ours_rows if r["day"] < DEV_END]
    k = _clip(math.sqrt(statistics.mean(r["z"] ** 2 for r in dev)), K_BOUNDS)
    ours = {r["day"].isoformat(): r for r in ours_rows}
    same = [r for r in rows if r["day"] in ours]
    out = {"computed_at": datetime.now(IST).isoformat(timespec="seconds"), "model": res["model"],
           "from": rows[0]["day"] if rows else None, "to": rows[-1]["day"] if rows else None,
           "kronos": _summary(rows),
           "ours_same_days": {"sessions": len(same),
                              "inside68_pct": round(sum(abs(ours[r["day"]]["z"] / k) <= Z68 for r in same) / len(same) * 100, 1) if same else None,
                              "inside95_pct": round(sum(abs(ours[r["day"]]["z"] / k) <= Z95 for r in same) / len(same) * 100, 1) if same else None},
           "rows": rows,
           "warning": ("Kronos was trained on candles from 45+ exchanges, very likely including NIFTY over these "
                       "years, so this check may score it on prices it has seen. Only the forward record is clean.")}
    path.write_text(json.dumps(out))
    return out


def _summary(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    n = len(rows)
    return {"sessions": n, "inside68_pct": round(sum(r["inside68"] for r in rows) / n * 100, 1),
            "inside95_pct": round(sum(r["inside95"] for r in rows) / n * 100, 1),
            "direction_hit_pct": round(sum(r["direction_hit"] for r in rows) / n * 100, 1),
            "median_abs_error": round(statistics.median(abs(r["error"]) for r in rows), 1)}


def view(db_path=None) -> dict:
    from storage import day_forecast_db as dfdb
    from storage import kronos_db as db
    daily, live = db.records("daily", db_path), db.records("live", db_path)
    scored_daily = [r for r in daily if r["outcome"]]
    scored_live = [r for r in live if r["outcome"]]
    ours = {r["target_day"]: r for r in dfdb.records() if r["outcome"]}
    pair = [r for r in scored_daily if r["target"] in ours]
    hind = json.loads(HINDCAST_PATH.read_text()) if HINDCAST_PATH.exists() else None
    if hind:
        hind = {k: v for k, v in hind.items() if k != "rows"}
    nxt = next((r for r in reversed(daily) if not r["outcome"]), None)
    our_next = next((r for r in reversed(dfdb.records()) if not r["outcome"]), None)
    return {
        "available": available(),
        "next_daily": nxt, "our_next": our_next["forecast"] if our_next and nxt and our_next["target_day"] == nxt["target"] else None,
        "live_latest": live[-1] if live else None,
        "forward": {
            "daily": _summary([r["outcome"] for r in scored_daily]),
            "live": _summary([r["outcome"] for r in scored_live]),
            "ours_same_days": ({"sessions": len(pair),
                                "inside68_pct": round(sum(ours[r["target"]]["outcome"]["inside68"] for r in pair) / len(pair) * 100, 1),
                                "inside95_pct": round(sum(ours[r["target"]]["outcome"]["inside95"] for r in pair) / len(pair) * 100, 1),
                                "direction_hit_pct": round(sum(ours[r["target"]]["outcome"]["lean_hit"] for r in pair) / len(pair) * 100, 1)}
                               if pair else None),
            "first_daily": scored_daily[0]["target"] if scored_daily else None,
            "first_live": scored_live[0]["target"] if scored_live else None,
        },
        "recent_daily": [{"target": r["target"], **r["outcome"], "band68": r["forecast"]["band68"],
                          "median": r["forecast"]["median"]} for r in reversed(scored_daily[-8:])],
        "recent_live": [{"target": r["target"], **r["outcome"], "median": r["forecast"]["median"]}
                        for r in reversed(scored_live[-8:])],
        "hindcast": hind,
        "note": ("Kronos is an open-source AI model trained on candles from 45+ exchanges. Its forecasts here are "
                 "written before the outcome and never edited, and scored beside the app's own. Its past check may "
                 "include prices it was trained on; only the forward record is a clean test. NIFTY has no volume, so "
                 "the model gets zeros. Nothing here is a reason to trade."),
    }
