"""Phases 9-12: the playbook, live tracking, similarity, the copilot, and
the recommendation that ties them together.

Here the question is consistency. Every one of these surfaces restates
something computed elsewhere — a verdict, a signal, an outcome. If two of
them disagree, the user is shown two versions of the same fact.
"""

import json
import math
import sqlite3
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from backtest.pattern_options import load_research
from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from market_data.kite_session import IST, _env
from quant.regime import classify_regime_series

from . import FAIL, PASS, SKIP, WARN, Result, check
from .checks_platform import _get, _server_up


# --- Phase 9: playbook --------------------------------------------------------

@check("9", "9.1", "The playbook shows the same verdicts and figures as the research that produced them")
def playbook_matches_research():
    if not _server_up():
        return Result(SKIP, "API not running on :8000")
    research = {p["strategy"]: p for p in (load_research() or {}).get("patterns", [])}
    status, body, _ = _get("/api/patterns/options")
    served = {p["strategy"]: p for p in json.loads(body).get("patterns", [])} if status == 200 else {}
    diffs = []
    for k, r in research.items():
        s = served.get(k)
        if not s:
            diffs.append((k, "missing from /api/patterns/options"))
            continue
        if s.get("status") != r.get("status"):
            diffs.append((k, f"status {s.get('status')} vs {r.get('status')}"))
        a, b = (s.get("holdout") or {}).get("avg_profit_per_lot_rs"), (r.get("holdout") or {}).get("avg_profit_per_lot_rs")
        if a != b:
            diffs.append((k, f"profit {a} vs {b}"))
    return Result(FAIL if diffs else PASS, f"{len(research)} patterns compared; {len(diffs)} disagree", {"diffs": diffs})


@check("9", "9.2", "The recommendation follows its own rule")
def recommendation_obeys_gate():
    from briefing.recommendation import build_recommendation
    rec = build_recommendation()
    research = {p["label"]: p for p in (load_research() or {}).get("patterns", [])}
    bar = rec["evidence_bar"]["min_t"]
    approved_formed = [c for c in rec.get("candidates", [])
                       if c.get("formed") and (research.get(c.get("label"), {}).get("status") == "APPROVED")
                       and (research.get(c.get("label"), {}).get("holdout_t_stat") or 0) >= bar]
    acts = rec["action"] in ("CONSIDER_CALL", "CONSIDER_PUT")
    ok = acts == bool(approved_formed)
    return Result(PASS if ok else FAIL,
                  f"action {rec['action']}; {len(approved_formed)} formed pattern(s) are APPROVED and clear t >= {bar}",
                  {"headline": rec.get("headline"), "patterns_judged": rec["evidence_bar"]["patterns_judged"]})


# --- Phase 10: live -----------------------------------------------------------

@check("10", "10.1", "'Formed today' on the dashboard is the same event the research measured")
def window_vs_full_history():
    """The dashboard evaluates patterns on a 420-bar window; the research
    evaluated them on 19 years. Recursive indicators seeded at different
    points can disagree, and a path-dependent one like Supertrend can flip
    outright — in which case 'formed today' is not the event whose record
    is being quoted."""
    from backtest.pattern_proximity import WINDOW_BARS
    df, _ = load_daily_data("^NSEI", 7000)
    full_regime = classify_regime_series(df)
    price = {k: v for k, v in STRATEGY_REGISTRY.items() if not k.startswith("pcr_")}
    full = {k: v["fn"](df, full_regime, **v["params"]).astype(bool) for k, v in price.items()}
    disagree = {}
    for end in range(len(df) - 120, len(df)):
        window = df.iloc[end - WINDOW_BARS + 1:end + 1]
        reg = classify_regime_series(window)
        for k, v in price.items():
            w = bool(v["fn"](window, reg, **v["params"]).astype(bool).iloc[-1])
            if w != bool(full[k].iloc[end]):
                disagree.setdefault(k, []).append((str(df.index[end].date()), "window" if w else "full history"))
    n = sum(len(v) for v in disagree.values())
    return Result(FAIL if n else PASS,
                  f"last 120 sessions x {len(price)} patterns; {n} day(s) where the two disagree on whether it formed",
                  {"by_pattern": {k: v[:6] for k, v in disagree.items()}})


@check("10", "10.2", "A published trigger level really does trigger the pattern")
def trigger_levels_real():
    """Take each trigger range the dashboard shows, append a candle closing
    just inside it and just outside it, and ask the real pattern function."""
    from backtest import pattern_proximity as pp
    prox = pp.pattern_proximity()
    df, _ = load_daily_data("^NSEI", 1400)
    window = df.iloc[-pp.WINDOW_BARS:]
    if str(window.index[-1].date()) != prox["as_of"]:
        window = window.iloc[:-1]
    prev = float(window["close"].iloc[-1])
    wick = float(((window["high"] - window[["open", "close"]].max(axis=1)) / window["close"]).median())
    nxt = window.index[-1] + pd.offsets.BDay(1)
    wrong, tested = [], 0
    for p in prox["patterns"]:
        for lo, hi in ((p.get("trigger") or {}).get("close_ranges_pct") or []):
            spec = STRATEGY_REGISTRY[p["strategy"]]
            for pct, expect in ((lo + 0.01, True), (hi - 0.01, True)):
                row = pd.DataFrame([pp._candidate(prev, pct, 0.0, "ordinary", wick)], index=[nxt])
                ext = pd.concat([window, row])
                got = bool(spec["fn"](ext, classify_regime_series(ext), **spec["params"]).astype(bool).iloc[-1])
                tested += 1
                if got != expect:
                    wrong.append((p["label"], pct, expect, got))
    return Result(FAIL if wrong else (PASS if tested else SKIP),
                  f"{tested} published trigger edges re-tested against the real pattern functions; {len(wrong)} wrong",
                  {"wrong": wrong})


@check("10", "10.3", "The forward log is write-once and was written before each outcome existed")
def forward_log_integrity():
    from storage.forward_log_db import DB_PATH, record_recommendation
    if not DB_PATH.exists():
        return Result(SKIP, "no forward log yet")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM recommendation_log ORDER BY as_of")]
    conn.close()
    problems = []
    for r in rows:
        recorded = datetime.fromisoformat(r["recorded_at"]).astimezone(IST)
        close = datetime.fromisoformat(r["as_of"] + "T15:30:00").replace(tzinfo=IST)
        if recorded < close:
            problems.append((r["as_of"], "recorded before that day's close"))
        next_open = close + timedelta(hours=17, minutes=45)
        if recorded > next_open + timedelta(days=4):
            problems.append((r["as_of"], f"recorded {recorded:%Y-%m-%d %H:%M}, days after the outcome began"))
        if r["action"] not in ("NO_TRADE", "CONSIDER_CALL", "CONSIDER_PUT"):
            problems.append((r["as_of"], f"unknown action {r['action']}"))
    # Write-once, tested on a scratch copy — never on the real file.
    import shutil
    import tempfile
    from pathlib import Path
    scratch = Path(tempfile.mkdtemp()) / "fl.db"
    shutil.copy(DB_PATH, scratch)
    if rows:
        first = rows[0]
        wrote = record_recommendation({"as_of": first["as_of"], "action": "CONSIDER_CALL", "regime": "X",
                                       "headline": "overwrite attempt"}, 1.0, db_path=scratch)
        c2 = sqlite3.connect(scratch)
        after = c2.execute("SELECT action FROM recommendation_log WHERE as_of=?", (first["as_of"],)).fetchone()[0]
        c2.close()
        if wrote or after != first["action"]:
            problems.append((first["as_of"], "an existing row was overwritten"))
    return Result(FAIL if problems else PASS, f"{len(rows)} rows; {len(problems)} problem(s)", {"problems": problems})


# --- Phase 11: similarity -----------------------------------------------------

@check("11", "11.1", "Every analog's outcome was already known, and no two are near-duplicates")
def analogs_known_and_spaced():
    from backtest import similarity as sim
    df, _ = load_daily_data("^NSEI", 7000)
    out = sim.similar_days(df)
    idx = {str(d.date()): i for i, d in enumerate(df.index)}
    q = len(df) - 1
    pos = sorted(idx[a["date"]] for a in out.get("analogs", []))
    unknown = [p for p in pos if p + sim.HORIZON > q]
    crowded = [(a, b) for a, b in zip(pos, pos[1:]) if b - a < sim.SPACING]
    recent = [p for p in pos if q - p <= 60]
    status = FAIL if unknown or crowded else (WARN if len(recent) > len(pos) / 4 else PASS)
    return Result(status, f"{len(pos)} analogs; {len(unknown)} with unknown outcomes, {len(crowded)} closer than "
                          f"{sim.SPACING} sessions, {len(recent)} from the last 60 sessions",
                  {"recent_analogs": [str(df.index[p].date()) for p in recent],
                   "note": "Analogs from the last few weeks share most of today's features by construction "
                           "(20-day return, 50-day EMA, 52-week high). They are not independent evidence."})


@check("11", "11.2", "The walk-forward test of analogs only ever uses outcomes known at the time")
def similarity_walk_forward_clean():
    from backtest import similarity as sim
    df, _ = load_daily_data("^NSEI", 7000)
    f, fwd = sim.features(df), sim.forward_returns(df)
    seen = []
    real = sim._neighbours

    def spy(fa, query, pool_end):
        nb = real(fa, query, pool_end)
        seen.append((query, max((i for i, _ in nb), default=-1)))
        return nb

    sim._neighbours = spy
    try:
        sim.walk_forward_test(df, f, fwd)
    finally:
        sim._neighbours = real
    leaks = [(str(df.index[t].date()), str(df.index[m].date())) for t, m in seen if m >= 0 and m + sim.HORIZON > t]
    return Result(FAIL if leaks else PASS,
                  f"{len(seen)} test points instrumented; {len(leaks)} used an analog whose outcome was not yet known",
                  {"leaks": leaks[:10]})


# --- Phase 12: copilot --------------------------------------------------------

@check("12", "12.1", "The composed explanation cannot contain an unverified number, in every context view")
def composer_numbers():
    from copilot.composer import compose
    from copilot.context import SCOPES, build_context
    from copilot.guard import unverified_numbers
    bad = {}
    for scope in (None, *SCOPES):
        ctx = build_context(scope=scope)
        text = compose(ctx)
        u = unverified_numbers(text, ctx)
        if u:
            bad[scope or "default"] = u
    return Result(FAIL if bad else PASS, f"{1 + len(SCOPES)} views composed; {len(bad)} contain a number not in their data",
                  {"unverified": bad})


@check("12", "12.2", "Every number the copilot is given traces back to a computed source")
def context_traces_to_source():
    """The number guard checks answers against the context. That is only
    worth something if the context itself holds nothing invented."""
    from backtest.pattern_proximity import pattern_proximity
    from briefing.recommendation import build_recommendation
    from copilot.context import HOW_IT_DECIDES, build_context
    from copilot.guard import numbers_in_data
    ctx = build_context(scope="pattern_record")
    sources = numbers_in_data([load_research(), build_recommendation(), pattern_proximity(), HOW_IT_DECIDES])
    from briefing.forward_log import forward_report
    sources |= numbers_in_data(forward_report())
    from backtest.pattern_options import LOT_SIZE
    sources |= {float(LOT_SIZE), 15.0, 30.0, 2024.0, 2026.0}
    orphan = sorted(v for v in numbers_in_data(ctx) if v not in sources and not (float(v).is_integer() and abs(v) <= 10))
    return Result(FAIL if orphan else PASS, f"{len(numbers_in_data(ctx))} numbers in the context; "
                                            f"{len(orphan)} not found in any computed source",
                  {"orphans": orphan[:20]})


@check("12", "12.3", "No secret has ever been written into the copilot's own records")
def copilot_records_clean():
    from storage.copilot_log_db import DB_PATH
    root = DB_PATH.parent
    secrets = [v for v in (_env(k) for k in ("LLM_API_KEY", "TYPESAFE_API_KEY", "KITE_API_SECRET")) if v and len(v) >= 12]
    files = [DB_PATH, root / "copilot_explanations.json", root / "daily_job.log"]
    found = [f.name for f in files if f.exists() and any(s.encode() in f.read_bytes() for s in secrets)]
    return Result(FAIL if found else PASS, f"{len(files)} record files searched for {len(secrets)} secret values; "
                                           f"{'found in ' + ', '.join(found) if found else 'none found'}")


@check("12", "12.4", "The guards still separate what they should, on the real model", live=True)
def guards_labelled_cases():
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).parent.parent / "scripts" / "check_guards.py"
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=900)
    tail = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-200:]
    return Result(PASS if p.returncode == 0 else FAIL, tail)
