"""The sentinel's engine: run the checks of one mode, open or update an
incident for each failure, try the repair when it is safe, tell the owner
once, and close the incident after two passes in a row.

A check never stops the run: one that raises is itself a finding. A repair
never runs during the nightly job (19:20 to "daily job done"), never more
than once in REPAIR_GAP, and in market hours only when it was registered as
safe there (a restart of a service that is not answering). Every attempt,
and every refusal, is written on the incident."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from sentinel import alerts
from storage import incidents_db as idb

REPAIR_GAP = timedelta(hours=2)
PASSES_TO_RESOLVE = 2
STATE_PATH = Path(__file__).parent.parent / "data" / "sentinel_state.json"
LOG_PATH = Path(__file__).parent.parent / "data" / "daily_job.log"


@dataclass(frozen=True)
class Finding:
    ok: bool
    severity: str = "warn"          # info | warn | critical
    summary: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Check:
    key: str
    area: str
    modes: tuple[str, ...]
    detect: Callable[[], Finding]
    repair: str | None = None
    auto: bool = True


REPAIRS: dict[str, tuple[Callable[[], tuple[bool, str]], bool]] = {}


def register_repair(name: str, fn: Callable[[], tuple[bool, str]], allow_in_session: bool = False) -> None:
    REPAIRS[name] = (fn, allow_in_session)


def session_open(now: datetime, holidays: set | None = None) -> bool:
    """09:15-15:30 IST on an NSE session day."""
    from market_data.nse_holidays import is_session, trading_holidays
    if holidays is None:
        try:
            holidays, _ = trading_holidays()
        except Exception:
            holidays = set()
    t = now.hour * 60 + now.minute
    return is_session(now.date(), holidays) and 9 * 60 + 15 <= t < 15 * 60 + 30


def job_alive(log_says_running: bool, pids: list[int]) -> bool:
    """Running means the log has a start without a done AND a job process
    exists: a job killed mid-run (a power cut) leaves only the first."""
    return log_says_running and bool(pids)


def nightly_job_running() -> bool:
    import subprocess

    from briefing.day_forecast import job_running as running
    from sentinel.checks_feeds import job_pids
    if not running(LOG_PATH):
        return False
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    return job_alive(True, job_pids(ps))


def may_repair(name: str, now: datetime, state: dict, in_session: bool, job_running: bool,
               allow_in_session: bool) -> tuple[bool, str]:
    if job_running:
        return False, "refused: the nightly job is running"
    if in_session and not allow_in_session:
        return False, "refused: market hours — waits for the close"
    last = state.get("repairs", {}).get(name)
    if last and now - datetime.fromisoformat(last) < REPAIR_GAP:
        return False, f"refused: tried at {datetime.fromisoformat(last):%H:%M}, next try after {REPAIR_GAP}"
    return True, ""


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _alert(send, kind: str, check: Check, summary: str, severity: str) -> bool:
    title = {"open": "Problem", "reminder": "Still open", "resolved": "Resolved"}[kind] + f" ({check.area})"
    body = summary if kind != "resolved" else f"{summary}: passing again"
    try:
        return bool(send(title, body, "high" if severity == "critical" and kind != "resolved" else "default"))
    except Exception:
        return False


def run(mode: str, checks: list[Check], now: datetime, db_path: Path | None = None, state_path: Path | None = None,
        send=None, in_session: bool | None = None, job_running: bool | None = None) -> dict:
    send = send or alerts.send
    state_path = state_path or STATE_PATH
    state = _load(state_path)
    state.setdefault("passes", {})
    state.setdefault("repairs", {})
    session = session_open(now) if in_session is None else in_session
    running = nightly_job_running() if job_running is None else job_running
    at = now.isoformat(timespec="seconds")
    open_by_key = {o["check_key"]: o for o in idb.open_incidents(db_path)}
    out = {"checked": 0, "failing": [], "opened": [], "resolved": []}
    for c in checks:
        if mode not in c.modes:
            continue
        out["checked"] += 1
        try:
            f = c.detect()
        except Exception as e:
            f = Finding(False, "warn", f"check broken: {type(e).__name__}: {_scrub(str(e))}")
        try:
            _handle(c, f, mode, now, at, state, out, open_by_key, db_path, send, session, running)
        except Exception as e:
            # The record could not be written (disk full, a locked database): say so directly.
            if not f.ok:
                out["failing"].append(c.key)
                _alert(send, "open", c, f"{f.summary} (could not be recorded: {type(e).__name__})", f.severity)
    state["checked_at"] = at
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1))
    return out


def _scrub(text: str) -> str:
    """No home paths in a message that may go to a public ntfy topic."""
    import os
    return text.replace(os.path.expanduser("~"), "~")


def _handle(c: Check, f: Finding, mode: str, now: datetime, at: str, state: dict, out: dict, open_by_key: dict,
            db_path, send, session: bool, running: bool) -> None:
    inc = open_by_key.get(c.key)
    if f.ok:
        if inc:
            n = state["passes"].get(c.key, 0) + 1
            state["passes"][c.key] = n
            if n >= PASSES_TO_RESOLVE:
                idb.add_event(inc["id"], "resolved", f"passed {n} runs in a row", at, db_path)
                _alert(send, "resolved", c, inc["summary"], inc["severity"])
                state["passes"].pop(c.key, None)
                out["resolved"].append(c.key)
        return
    out["failing"].append(c.key)
    state["passes"].pop(c.key, None)
    detail = f.summary + (f" · {json.dumps(f.evidence, default=str)[:300]}" if f.evidence else "")
    if inc:
        iid = inc["id"]
        idb.add_event(iid, "seen", detail, at, db_path)
    else:
        iid = idb.open_incident(c.key, c.area, f.severity, f.summary, at, db_path)
        idb.add_event(iid, "seen", detail, at, db_path)
        inc = {"id": iid, "last_alert_at": None, "severity": f.severity}
        out["opened"].append(c.key)
    if c.repair and c.auto and c.repair in REPAIRS:
        fn, allow = REPAIRS[c.repair]
        ok, why = may_repair(c.repair, now, state, session, running, allow)
        if ok:
            state["repairs"][c.repair] = at
            try:
                done, msg = fn()
            except Exception as e:
                done, msg = False, f"raised {e}"
            why = f"{c.repair}: {'ok' if done else 'failed'}, {msg}"
        else:
            why = f"{c.repair}: {why}"
        idb.add_event(iid, "repair", why, at, db_path)
    kind = alerts.due(inc, now)
    if kind:
        _alert(send, kind, c, f.summary, f.severity)
        idb.add_event(iid, "alert", kind, at, db_path)
