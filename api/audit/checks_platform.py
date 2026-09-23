"""Phases 1-4: repository, frontend, API and the provider abstraction.

Nothing here is about whether a pattern works. It is about whether the
plumbing leaks — a secret into git, a NaN into JSON a browser cannot parse,
a stack trace into an error message, a bad tick into a live candle.
"""

import json
import math
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from market_data.kite_session import _env

from . import FAIL, PASS, SKIP, WARN, Result, check

ROOT = Path(__file__).parent.parent.parent
API = "http://127.0.0.1:8000"
SECRET_KEYS = ("KITE_API_SECRET", "LLM_API_KEY", "TYPESAFE_API_KEY")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


# --- Phase 1 -----------------------------------------------------------------

@check("1", "1.1", "No real secret value appears in any tracked file or anywhere in git history")
def secrets_not_in_git():
    """Searches for the actual values in api/.env, not a pattern that looks
    like a key. Only file names and key names are ever reported — never a
    value, not even a prefix."""
    values = {k: _env(k) for k in SECRET_KEYS}
    values = {k: v for k, v in values.items() if v and len(v) >= 12}
    if not values:
        return Result(SKIP, "no secrets configured to search for")
    hits = {}
    for key, val in values.items():
        tracked = _git("grep", "-l", "-F", val).split()
        history = _git("log", "--all", "--oneline", "-S", val).strip().splitlines()
        if tracked or history:
            hits[key] = {"tracked_files": tracked, "commits": len(history)}
    return Result(FAIL if hits else PASS,
                  f"searched {len(values)} secret values across tracked files and all history: "
                  f"{'FOUND in ' + ', '.join(hits) if hits else 'none found'}",
                  {"found": hits})


@check("1", "1.2", "Secrets and generated data are git-ignored; nothing large is tracked")
def ignores_hold():
    must_ignore = ["api/.env", "api/data/forward_log.db", "api/data/nifty_options.db",
                   "api/data/copilot_log.db", "api/data/nifty_bars.db"]
    not_ignored = [p for p in must_ignore
                   if subprocess.run(["git", "check-ignore", "-q", p], cwd=ROOT).returncode != 0]
    big = []
    for line in _git("ls-files", "-s").splitlines():
        path = line.split("\t")[-1]
        f = ROOT / path
        if f.exists() and f.stat().st_size > 1_000_000:
            big.append((path, f.stat().st_size))
    return Result(FAIL if not_ignored else (WARN if big else PASS),
                  f"{len(must_ignore) - len(not_ignored)}/{len(must_ignore)} protected paths ignored; "
                  f"{len(big)} tracked file(s) over 1 MB",
                  {"not_ignored": not_ignored, "large_tracked": big})


@check("1", "1.3", "The one irreplaceable file has a backup")
def forward_log_backed_up():
    live = ROOT / "api" / "data" / "forward_log.db"
    if not live.exists():
        return Result(SKIP, "no forward log yet")
    copies = [p for p in ROOT.rglob("forward_log*.db*") if p != live and ".venv" not in p.parts]
    home = Path.home()
    copies += [p for d in (home / "Library" / "Mobile Documents", home / "Documents")
               if d.exists() for p in d.glob("**/forward_log*backup*") if p.is_file()][:5]
    return Result(PASS if copies else WARN,
                  f"forward_log.db cannot be regenerated; {len(copies)} backup cop(ies) found",
                  {"copies": [str(p) for p in copies]})


# --- Phases 2-3 ----------------------------------------------------------------

def _get(path: str, timeout: int = 180):
    t0 = time.time()
    try:
        with urllib.request.urlopen(API + path, timeout=timeout) as r:
            return r.status, r.read().decode(), round(time.time() - t0, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), round(time.time() - t0, 1)


def _server_up() -> bool:
    try:
        return _get("/health", timeout=5)[0] == 200
    except Exception:
        return False


ENDPOINTS = [
    "/api/snapshot", "/api/indicators", "/api/candles", "/api/research/compare", "/api/strategies/playbook",
    "/api/briefing", "/api/options/chain", "/api/options/archive", "/api/live", "/api/recommendation",
    "/api/forward_log", "/api/bars/archive", "/api/patterns/options", "/api/patterns/today",
    "/api/live/patterns", "/api/similarity", "/api/intraday/research", "/api/copilot/status",
    "/api/copilot/record", "/api/copilot/composed", "/api/zerodha/status",
]


def _strict(text: str):
    """Python's json module happily emits NaN and Infinity. A browser's
    JSON.parse rejects them, so the page breaks on data the API calls valid."""
    def bad(token):
        raise ValueError(f"non-standard JSON token {token}")
    return json.loads(text, parse_constant=bad)


@check("3", "3.1", "Every endpoint answers with JSON a browser can actually parse (no NaN or Infinity)")
def endpoints_strict_json():
    if not _server_up():
        return Result(SKIP, "API not running on :8000")
    broken, slow, timings = [], [], {}
    for ep in ENDPOINTS:
        status, body, secs = _get(ep)
        timings[ep] = secs
        if status >= 500 and ep in ("/api/options/chain", "/api/live"):
            continue  # need a live market or login; covered elsewhere
        try:
            _strict(body)
        except ValueError as e:
            broken.append((ep, status, str(e)[:80]))
        if secs > 30:
            slow.append((ep, secs))
    return Result(FAIL if broken else (WARN if slow else PASS),
                  f"{len(ENDPOINTS)} endpoints; {len(broken)} return JSON a browser would reject, "
                  f"{len(slow)} slower than 30s",
                  {"broken": broken, "slow": slow, "timings": timings})


@check("3", "3.2", "Error responses never carry a traceback or a secret")
def errors_do_not_leak():
    if not _server_up():
        return Result(SKIP, "API not running on :8000")
    probes = ["/api/validation/definitely_not_a_strategy", "/api/strategies/nope/history",
              "/api/candles?provider=nonsense", "/api/candles?days=-5", "/api/similarity?symbol=%27%3B--"]
    secrets = [v for v in (_env(k) for k in SECRET_KEYS) if v and len(v) >= 12]
    leaks = []
    for p in probes:
        status, body, _ = _get(p, timeout=60)
        if "Traceback" in body or 'File "/' in body:
            leaks.append((p, status, "traceback"))
        if any(s in body for s in secrets):
            leaks.append((p, status, "SECRET VALUE"))
        if status >= 500:
            leaks.append((p, status, "unhandled 5xx on bad input"))
    return Result(FAIL if any(l[2] != "unhandled 5xx on bad input" for l in leaks) else (WARN if leaks else PASS),
                  f"{len(probes)} malformed requests; {len(leaks)} problem(s)", {"problems": leaks})


@check("3", "3.3", "CORS admits only the local dashboard")
def cors_locked():
    if not _server_up():
        return Result(SKIP, "API not running on :8000")
    req = urllib.request.Request(API + "/health", headers={"Origin": "https://evil.example"})
    with urllib.request.urlopen(req, timeout=10) as r:
        allowed = r.headers.get("access-control-allow-origin")
    return Result(FAIL if allowed in ("*", "https://evil.example") else PASS,
                  f"a foreign origin gets access-control-allow-origin={allowed!r}")


@check("2", "2.1", "The dashboard never falls back to invented data (I2)")
def no_mock_fallbacks():
    src = ROOT / "web" / "src"
    offenders = []
    for f in src.rglob("*.ts*"):
        text = f.read_text()
        if re.search(r"from ['\"].*mock-data['\"]", text) or re.search(r"\bMOCK_|mockData\b", text):
            offenders.append(str(f.relative_to(ROOT)))
    return Result(FAIL if offenders else PASS,
                  f"{len(offenders)} component(s) import mock data", {"files": offenders})


@check("2", "2.2", "The production build succeeds (catches what tsc and eslint cannot)")
def next_build():
    try:
        urllib.request.urlopen("http://127.0.0.1:3000", timeout=3)
        return Result(SKIP, "dev server is running on :3000 — a production build would overwrite its .next")
    except Exception:
        pass
    # The nightly job runs from launchd, whose PATH has no node. A missing
    # toolchain is not a broken build, and alerting on it nightly would
    # teach everyone to ignore the alert.
    npx = shutil.which("npx")
    if npx is None:
        return Result(SKIP, "npx is not on PATH (launchd's environment) — run the audit from a shell to build")
    proc = subprocess.run([npx, "next", "build"], cwd=ROOT / "web", capture_output=True, text=True, timeout=600)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
    return Result(PASS if proc.returncode == 0 else FAIL,
                  "next build " + ("succeeded" if proc.returncode == 0 else "FAILED"), {"tail": tail})


# --- Phase 4 -----------------------------------------------------------------

def _contract(candles) -> list[str]:
    problems = []
    ts = [c.timestamp for c in candles]
    if ts != sorted(ts):
        problems.append("not sorted by time")
    if len(ts) != len(set(ts)):
        problems.append(f"{len(ts) - len(set(ts))} duplicate timestamps")
    for c in candles:
        vals = (c.open, c.high, c.low, c.close)
        if any(v is None or math.isnan(v) for v in vals):
            problems.append(f"NaN in {c.timestamp}")
            break
    return problems


@check("4", "4.1", "Every provider honours the contract: sorted, unique, no NaN")
def providers_contract():
    from market_data import CSVProvider, YFinanceProvider
    from market_data.bar_archive import ArchiveProvider

    sample = Path(__file__).parent.parent / "market_data" / "sample_data" / "nifty_synthetic_15m.csv"
    end = date.today()
    cases = {
        "csv": (CSVProvider(sample), "15m", date(2000, 1, 1), end),
        "yfinance": (YFinanceProvider(), "1d", end - timedelta(days=400), end),
        "archive 1d": (ArchiveProvider(), "1d", end - timedelta(days=400), end),
        "archive 15m": (ArchiveProvider(), "15m", end - timedelta(days=20), end),
    }
    out = {}
    for name, (prov, tf, a, b) in cases.items():
        try:
            candles = prov.get_ohlc("^NSEI", tf, a, b)
            out[name] = {"bars": len(candles), "problems": _contract(candles)}
        except Exception as e:
            out[name] = {"bars": 0, "problems": [f"{type(e).__name__}: {e}"]}
    bad = {k: v for k, v in out.items() if v["problems"] or not v["bars"]}
    return Result(FAIL if bad else PASS, f"{len(cases)} providers checked; {len(bad)} broke the contract", out)


@check("4", "4.2", "Served 15-minute bars never exceed the day's official range")
def served_bars_clean():
    """The source archive has a few bad ticks (check 0.3). Whatever serves
    intraday bars to research or to live tracking must not pass them on."""
    from backtest.intraday import load_intraday

    from .checks_data import SPIKE_POINTS, _bars
    daily = {r["ts"][:10]: r for r in _bars("1d")}
    served = load_intraday()
    over = []
    for d, bars in served.items():
        if d not in daily:
            continue
        hi = max(b["high"] for b in bars.values())
        lo = min(b["low"] for b in bars.values())
        if hi - daily[d]["high"] > SPIKE_POINTS or daily[d]["low"] - lo > SPIKE_POINTS:
            over.append((d, round(hi - daily[d]["high"], 1), round(daily[d]["low"] - lo, 1)))
    return Result(FAIL if over else PASS,
                  f"{len(served)} sessions served to intraday research; {len(over)} still carry a bad tick",
                  {"sessions": over})


# --- Phase 15: deployment ------------------------------------------------------

LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
SERVICES = ("com.niftycopilot.api", "com.niftycopilot.web")


@check("15", "15.1", "The deployed app listens to this Mac and nothing else")
def services_are_local_only():
    """It holds a live broker session, a personal journal and a paper book.
    Bound to 0.0.0.0 it would answer anything on the network — a coffee-shop
    Wi-Fi included. Both services must name 127.0.0.1 explicitly, and the API
    must admit only the local dashboard."""
    plists = {s: LAUNCH_AGENTS / f"{s}.plist" for s in SERVICES}
    installed = {s: p for s, p in plists.items() if p.exists()}
    if not installed:
        return Result(SKIP, "services not installed — ./scripts/install_app_services.sh")

    problems, detail = [], {}
    for name, path in installed.items():
        text = path.read_text()
        local = "127.0.0.1" in text
        wide = "0.0.0.0" in text
        detail[name] = {"binds_localhost": local, "binds_all_interfaces": wide}
        if not local or wide:
            problems.append(name)

    cors = (ROOT / "api" / "main.py").read_text()
    origins = re.search(r"allow_origins=\[(.*?)\]", cors, re.S)
    origin_text = origins.group(1) if origins else ""
    detail["cors_origins"] = origin_text.strip()
    if "*" in origin_text or "0.0.0.0" in origin_text:
        problems.append("CORS")

    listening = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    for port in ("3000", "8000"):
        for line in listening.splitlines():
            if f":{port} (LISTEN)" in line and "127.0.0.1" not in line:
                problems.append(f"port {port} listening beyond localhost")
                detail[f"port_{port}"] = line.split()[-2:]

    return Result(FAIL if problems else PASS,
                  f"{len(installed)} service(s) installed; "
                  + ("local only" if not problems else f"exposed: {', '.join(problems)}"),
                  detail)


@check("15", "15.2", "The service logs never carry a secret")
def service_logs_have_no_secrets():
    """uvicorn and Next write to files that get read, pasted and shared. A
    key reaching them is a key leaked, whatever .gitignore says."""
    values = {k: _env(k) for k in SECRET_KEYS}
    values = {k: v for k, v in values.items() if v and len(v) >= 12}
    logs = [ROOT / "api" / "data" / name for name in
            ("api_service.log", "web_service.log", "daily_job.log", "login_check.log")]
    present = [p for p in logs if p.exists()]
    if not values:
        return Result(SKIP, "no secrets configured to search for")
    found = []
    for path in present:
        text = path.read_text(errors="ignore")
        found += [f"{k} in {path.name}" for k, v in values.items() if v in text]
    return Result(FAIL if found else PASS,
                  f"{len(present)} log file(s) searched for {len(values)} secret value(s); "
                  + ("none found" if not found else "LEAKED"),
                  {"leaked": found, "files": [p.name for p in present]})
