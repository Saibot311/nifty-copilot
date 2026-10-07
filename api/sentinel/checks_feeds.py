"""Feed, job, time and security checks (spec §3.2: F1, F2, F4, J1, J2, J3,
T1, T2, T3, S1, S2, S3). F3, the Kite login, is the existing 08:45 check,
whose reminder now reaches the phone through sentinel/alerts.py."""

import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from sentinel.core import Check, Finding, register_repair

API = Path(__file__).parent.parent
DATA = API / "data"
JOB_LOG = DATA / "daily_job.log"
STATE = DATA / "sentinel_feeds.json"
JOB_BUDGET = timedelta(hours=4)
HOLIDAYS_AHEAD = timedelta(days=60)
RATE_CARD_MAX_AGE = timedelta(days=180)
CHAIN_FIELDS = ("lastPrice", "openInterest", "impliedVolatility", "buyPrice1", "sellPrice1")
QUOTE_FIELDS = ("last", "open", "high", "low", "market_time")
HOSTS = {"yahoo": "https://query1.finance.yahoo.com", "gdelt": "https://api.gdeltproject.org",
         "nse": "https://www.nseindia.com"}
SECURITY_ROWS = ("1.1", "15.1", "15.2")


# --- pure checks ---------------------------------------------------------------------

def snapshots_failing(log_tail: list[str], in_session: bool) -> Finding:
    runs = [line for line in log_tail if re.match(r"\d\d:\d\d ", line) and "intraday record" not in line][-3:]
    failing = in_session and len(runs) == 3 and all("FAILED" in r for r in runs)
    return Finding(not failing, "warn", "The five-minute option recordings failed three times running: "
                   + (runs[-1][:160] if runs else ""), {"last_runs": runs})


def chain_shape(payload: dict) -> Finding:
    rec = (payload or {}).get("records") or {}
    missing = [k for k in ("underlyingValue", "expiryDates", "data") if not rec.get(k)]
    rows = rec.get("data") or []
    for side in ("CE", "PE"):
        row = next((r[side] for r in rows if r.get(side)), None)
        if row is None:
            missing.append(f"data[].{side}")
        else:
            missing += [f"{side}.{k}" for k in CHAIN_FIELDS if k not in row]
    return Finding(not missing, "critical", "NSE's option-chain format changed: missing " + ", ".join(missing),
                   {"missing": missing})


def quote_shape(q: dict) -> Finding:
    missing = [k for k in QUOTE_FIELDS if k not in (q or {})]
    return Finding(not missing, "critical", "NSE's quote format changed: missing " + ", ".join(missing),
                   {"missing": missing})


def hosts_down(results: dict[str, bool], history: dict[str, int]) -> tuple[Finding, dict[str, int]]:
    hist = {h: (0 if up else history.get(h, 0) + 1) for h, up in results.items()}
    down = [h for h, n in hist.items() if n >= 2]
    return Finding(not down, "warn", "Down two nights running: " + ", ".join(down), {"nights_down": hist}), hist


def job_missed(log_text: str, last_session: date, now: datetime) -> Finding:
    if now.hour < 8:
        return Finding(True, "info", "before 08:00")
    after = datetime.combine(last_session, datetime.min.time()).replace(hour=19, minute=30)
    done = [datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            for m in re.finditer(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] daily job done", log_text)]
    ok = any(d >= after for d in done)
    return Finding(ok, "warn", f"The nightly job did not finish after the {last_session:%-d %b} session; "
                   "the catch-up starts it", {"last_done": max(done).isoformat() if done else None})


def job_overrun(started_at: datetime | None, now: datetime, step: str) -> Finding:
    late = started_at is not None and now - started_at > JOB_BUDGET
    return Finding(not late, "warn", f"The nightly job has run over {JOB_BUDGET.seconds // 3600} h; it is on: {step}",
                   {"started_at": started_at.isoformat() if started_at else None})


def job_twice(pids: list[int]) -> Finding:
    return Finding(len(pids) <= 1, "warn", f"{len(pids)} nightly jobs running at once", {"pids": pids})


def catch_up_allowed(state: dict, today: date, running: bool) -> bool:
    return not running and state.get("catch_up_on") != today.isoformat()


def holidays_known(known_through: date | None, today: date) -> Finding:
    ok = known_through is not None and known_through >= today + HOLIDAYS_AHEAD
    return Finding(ok, "warn", "NSE's holiday list does not reach two months ahead (it ends "
                   f"{known_through or 'nowhere'}): next year's list is not out yet, or NSE did not answer",
                   {"known_through": str(known_through)})


def lot_size(exchange_lot: int, configured: int) -> Finding:
    return Finding(exchange_lot == configured, "critical",
                   f"NIFTY's lot size is now {exchange_lot}, the code uses {configured}: costs and sizing are off "
                   "until backtest/options_engine.py LOT_SIZE is changed", {"exchange": exchange_lot, "code": configured})


def rate_card_age(rates_as_of: str, today: date) -> Finding:
    age = today - date.fromisoformat(rates_as_of)
    return Finding(age <= RATE_CARD_MAX_AGE, "warn", f"The rate card (STT, charges) was last checked {rates_as_of}, "
                   f"{age.days} days ago: re-verify against Zerodha and NSE", {"days": age.days})


def audit_security(rows: list[dict]) -> Finding:
    bad = [f"{r['id']} {r.get('title', '')}".strip() for r in rows
           if r.get("id") in SECURITY_ROWS and r.get("status") == "FAIL"]
    return Finding(not bad, "critical", "Security check failed in the audit: " + "; ".join(bad), {"failed": bad})


def npm_audit(report: dict) -> Finding:
    v = (report.get("metadata") or {}).get("vulnerabilities") or {}
    n = int(v.get("high", 0)) + int(v.get("critical", 0))
    return Finding(n == 0, "warn", f"{n} high or critical vulnerabilities in the dashboard's packages: "
                   "run npm audit in web/", {"vulnerabilities": v})


# --- state, measuring, repairs ---------------------------------------------------------

def _state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1))


def _now():
    from market_data.kite_session import IST
    return datetime.now(IST)


def _job_pids() -> list[int]:
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10).stdout
    return [int(line.split()[0]) for line in out.splitlines() if "scripts/daily_job.py" in line]


def _job_started() -> tuple[datetime | None, str]:
    from sentinel.core import nightly_job_running
    if not nightly_job_running() or not JOB_LOG.exists():
        return None, ""
    lines = JOB_LOG.read_text(errors="replace").splitlines()
    start = next((m for line in reversed(lines) if (m := re.match(r"\[(.{19})\] daily job start", line))), None)
    step = next((line[22:].strip() for line in reversed(lines) if re.match(r"\[.{19}\]   \S", line)), "")
    if not start:
        return None, step
    return datetime.strptime(start.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_now().tzinfo), step


def _last_session(today: date) -> date:
    from market_data.nse_holidays import is_session, trading_holidays
    hol, _ = trading_holidays()
    d = today - timedelta(days=1)
    while not is_session(d, hol):
        d -= timedelta(days=1)
    return d


def _catch_up() -> tuple[bool, str]:
    from sentinel.core import nightly_job_running
    state = _state()
    today = _now().date()
    if not catch_up_allowed(state, today, nightly_job_running()):
        return False, "already started today, or the job is running"
    subprocess.Popen([sys.executable, str(API / "scripts" / "daily_job.py")], cwd=API, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state["catch_up_on"] = today.isoformat()
    _save(state)
    return True, "the nightly job was started"


register_repair("catch_up_job", _catch_up)


def _snapshots() -> Finding:
    from sentinel.core import session_open
    log = DATA / "snapshots.launchd.log"
    tail = log.read_text(errors="replace").splitlines()[-30:] if log.exists() else []
    return snapshots_failing(tail, session_open(_now()))


def _canary() -> Finding:
    from market_data.live_quote import _session, live_index_quote
    chain = chain_shape(_session().index_option_chain("NIFTY"))
    return chain if not chain.ok else quote_shape(live_index_quote() or {})


def _hosts() -> Finding:
    import requests
    results = {}
    for name, url in HOSTS.items():
        try:
            requests.head(url, timeout=10)
            results[name] = True
        except Exception:
            results[name] = False
    state = _state()
    finding, state["hosts"] = hosts_down(results, state.get("hosts", {}))
    _save(state)
    return finding


def _holidays() -> Finding:
    from market_data.nse_holidays import trading_holidays
    hol, known = trading_holidays()
    return holidays_known(max(hol) if known and hol else None, _now().date())


def _lot() -> Finding:
    from backtest.options_engine import LOT_SIZE
    from market_data.kite_session import authenticated_client
    try:
        rows = authenticated_client().instruments("NFO")
    except Exception as e:
        return Finding(True, "info", f"lot size not checked: Kite not available ({type(e).__name__})")
    lot = next((int(r["lot_size"]) for r in rows if r.get("name") == "NIFTY" and r.get("segment") == "NFO-OPT"), None)
    return lot_size(lot, LOT_SIZE) if lot else Finding(True, "info", "lot size not found in Kite's list")


def _rate_card() -> Finding:
    from backtest.options_engine import COSTS_VERSION
    return rate_card_age(COSTS_VERSION, _now().date())


def _security() -> Finding:
    try:
        rows = json.loads((DATA / "audit_results.json").read_text())
    except (OSError, ValueError):
        return Finding(True, "info", "no audit results yet")
    return audit_security(rows)


def _npm() -> Finding:
    if _now().weekday() != 6:
        return Finding(True, "info", "checked on Sundays")
    out = subprocess.run(["npm", "audit", "--omit=dev", "--json"], cwd=API.parent / "web", capture_output=True,
                         text=True, timeout=120).stdout
    return npm_audit(json.loads(out or "{}"))


def feed_checks() -> list[Check]:
    return [
        Check("snapshots", "feeds", ("fast",), _snapshots),
        Check("nse_format", "feeds", ("deep",), _canary),
        Check("hosts", "feeds", ("deep",), _hosts),
        Check("job_missed", "jobs", ("fast",),
              lambda: job_missed(JOB_LOG.read_text(errors="replace") if JOB_LOG.exists() else "",
                                 _last_session(_now().date()), _now()), "catch_up_job"),
        Check("job_overrun", "jobs", ("fast",), lambda: job_overrun(*_job_started_now())),
        Check("job_twice", "jobs", ("fast",), lambda: job_twice(_job_pids())),
        Check("holidays", "time", ("deep",), _holidays),
        Check("lot_size", "time", ("deep",), _lot),
        Check("rate_card", "time", ("deep",), _rate_card),
        Check("security", "security", ("deep",), _security),
        Check("packages", "security", ("deep",), _npm),
    ]


def _job_started_now() -> tuple[datetime | None, datetime, str]:
    started, step = _job_started()
    return started, _now(), step
