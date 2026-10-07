"""Check that every card's data is as current as the market clock says, and
keep it so. Started by the watchdog (scripts/health_watch.py) every ten
minutes; one run at a time.

  1. Fetch every source the dashboard reads, from the running API, and judge
     each against the market clock (briefing/freshness.py).
  2. Restart a service that is running older code or an older build than is
     on disk — outside market hours; during a session, say so and wait.
  3. Run the steps that bring a behind source up to date (bars, options
     archive, IV, research, the forecast, the paper book), each at most every
     two hours, never while the nightly job is running.
  4. Notify once a day for each source still behind.
  5. Write data/freshness.json for /api/freshness and the dashboard.

    cd api && .venv/bin/python scripts/freshness_check.py            # check, fix, write
    cd api && .venv/bin/python scripts/freshness_check.py --no-fix   # check and write only
"""

import argparse
import fcntl
import json
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

API = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API))

from briefing import freshness as fr  # noqa: E402
from briefing.day_forecast import job_running  # noqa: E402
from market_data.kite_session import IST  # noqa: E402

BASE = "http://127.0.0.1:8000"
OUT = API / "data" / "freshness.json"
STATE = API / "data" / "freshness_state.json"
LOG = API / "data" / "freshness.log"
LOCK = API / "data" / "freshness.lock"
PY = sys.executable
# Folders the API process never imports: scripts run as their own processes.
NOT_LOADED_BY_API = (".venv", "tests", "data", "__pycache__", "scripts")


def fixes(today: date) -> dict[str, list[list[str]]]:
    return {
        "kite_bars": [[PY, "scripts/backfill_bars.py", "--timeframe", tf] for tf in ("1d", "15m", "5m")],
        "options": [[PY, "scripts/backfill_options.py", "--start", (today - timedelta(days=10)).isoformat()]],
        "iv": [[PY, "scripts/iv_research.py"]],
        "research": [[PY, "scripts/pattern_options.py"], [PY, "scripts/structural_research.py"],
                     [PY, "scripts/replication.py"]],
        # The Market tab's studies read Yahoo's daily bars; a night Yahoo
        # answered with none (5 Oct 2026) left its option prices at 1 Oct.
        "market": [[PY, "scripts/market_research.py"]],
        "forecast": [[PY, "scripts/day_forecast.py"]],
        "breakouts": [[PY, "scripts/breakout_levels.py"]],
        "paper": [[PY, "scripts/paper_observe.py"]],
    }


def log(msg: str) -> None:
    line = f"[{datetime.now(IST).isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def fetch(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=90) as r:
            return json.loads(r.read())
    except Exception:
        return None


def started_at(port: int) -> datetime | None:
    """When the process listening on `port` started."""
    try:
        pid = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True,
                             text=True, timeout=10).stdout.split()[0]
        raw = subprocess.run(["ps", "-o", "lstart=", "-p", pid], capture_output=True, text=True, timeout=10).stdout
        return datetime.strptime(" ".join(raw.split()), "%a %b %d %H:%M:%S %Y").replace(tzinfo=IST)
    except Exception:
        return None


def restart(label: str) -> bool:
    """As the watchdog restarts a service: launchd's kickstart."""
    import os
    done = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0


def newest(paths) -> datetime | None:
    times = [p.stat().st_mtime for p in paths if p.exists()]
    return datetime.fromtimestamp(max(times), IST) if times else None


def services(now: datetime, holidays: set, allow_restart: bool) -> list[dict]:
    """Each service against what is on disk; restarted when behind and allowed."""
    root = API.parent
    py = [p for p in API.rglob("*.py") if not any(x in p.relative_to(API).parts for x in NOT_LOADED_BY_API)]
    checks = [("com.niftycopilot.api", 8000, newest(py), "its Python code"),
              ("com.niftycopilot.web", 3000, newest([root / "web" / ".next" / "BUILD_ID"]), "its build")]
    out = []
    for label, port, disk, what in checks:
        start = started_at(port)
        row = {"service": label, "started": start and start.isoformat(timespec="minutes"),
               "on_disk": disk and disk.isoformat(timespec="minutes"), "behind": False, "action": None}
        if start and disk and fr.service_behind(start, disk):
            row["behind"] = True
            if allow_restart and fr.restart_now(now, holidays):
                ok = restart(label)
                row["action"] = "restarted" if ok else "restart failed"
                log(f"{label} was running code older than {what} on disk: " + row["action"])
            else:
                row["action"] = "restart after the session" if allow_restart else "not restarted (--no-fix)"
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fix", action="store_true", help="check and write the report; change nothing")
    a = ap.parse_args()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another check is running", flush=True)
        return 0

    from market_data.nse_holidays import trading_holidays
    holidays, _known = trading_holidays()
    now = datetime.now(IST)
    paths = sorted({s.path for s in fr.SOURCES})
    with ThreadPoolExecutor(6) as pool:
        payloads = dict(zip(paths, pool.map(fetch, paths)))
    ev = fr.evaluate(payloads, now, holidays)
    ev["services"] = services(now, holidays, allow_restart=not a.no_fix)

    try:
        state = json.loads(STATE.read_text())
    except Exception:
        state = {}
    tried, notified = state.setdefault("tried", {}), state.setdefault("notified", {})
    running = job_running(API / "data" / "daily_job.log")
    ran = []
    if not a.no_fix:
        steps = fixes(now.date())
        for name in fr.plan_fixes(ev):
            last = fr.parse_time(tried.get(name))
            if not fr.may_fix(name, now, running, last):
                continue
            if name == "kite_bars":
                from market_data.kite_session import session_status
                if not session_status()["logged_in"]:
                    log("kite bars needed but the Kite login has lapsed: log in from the dashboard")
                    continue
            tried[name] = now.isoformat(timespec="seconds")
            codes = [subprocess.run(cmd, cwd=API, capture_output=True, timeout=3600).returncode for cmd in steps[name]]
            ran.append({"fix": name, "ok": all(c == 0 for c in codes)})
            log(f"fix {name}: " + ("done" if all(c == 0 for c in codes) else f"exit codes {codes}"))
    ev["fixes_run"] = ran
    ev["nightly_job_running"] = running

    behind = [s for s in ev["sources"] if s["status"] == "behind"]
    today = now.date().isoformat()
    fresh_news = [s for s in behind if notified.get(s["key"]) != today]
    if fresh_news and not a.no_fix:
        from sentinel.alerts import send
        send("Data behind", f"{len(behind)} card(s) behind: " + ", ".join(s["card"] for s in behind[:4]))
        for s in fresh_news:
            notified[s["key"]] = today
    for s in behind:
        log(f"behind: {s['card']} ({s['key']}): {s['reason']}")
    STATE.write_text(json.dumps(state, indent=1))
    OUT.write_text(json.dumps(ev, indent=1))
    print(f"{ev['current']} current, {ev['behind']} behind, {ev['unavailable']} unavailable, "
          f"{ev['on_demand']} on demand; fixes run: {[r['fix'] for r in ran] or 'none'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
