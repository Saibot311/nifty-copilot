"""Machine and process checks (spec §3.2: P2, P3, P4, D1, D5, M1, M2).
Each check is a pure function of what was measured, tested at the spec's
thresholds, and a thin wrapper that measures it here."""

import gzip
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from sentinel.core import Check, Finding, register_repair

DATA = Path(__file__).parent.parent / "data"
API_URL, WEB_URL = "http://127.0.0.1:8000/health", "http://127.0.0.1:3000/"
SLOW_API_S, SLOW_RENDER_S, MEMORY_MB, CLOCK_S = 10.0, 8.0, 1536.0, 30.0
DISK_WARN_GB, DISK_CRITICAL_GB = 5.0, 2.0
LOG_LIMIT = 50 * 1024 * 1024
LABELS = {"api": "com.niftycopilot.api", "web": "com.niftycopilot.web"}
SLEEP_FIX = "sudo pmset -c sleep 0 disksleep 0 autorestart 1 womp 1"


# --- pure checks ---------------------------------------------------------------------

def slow_api(latencies_s: list[float]) -> Finding:
    s = sorted(latencies_s)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))] if s else float("inf")
    return Finding(p95 <= SLOW_API_S, "critical", f"The API is answering slowly: {p95:.1f} s (over {SLOW_API_S:.0f} s)",
                   {"latencies_s": [round(x, 2) for x in latencies_s]})


def rss_by_service(ps_text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in ps_text.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if not m:
            continue
        kb, cmd = int(m.group(1)), m.group(2)
        key = "api" if "uvicorn main:app" in cmd else "web" if ("node server.mjs" in cmd or "next-server" in cmd) else None
        if key:
            out[key] = out.get(key, 0.0) + kb / 1024
    return out


def memory(rss_mb: dict[str, float]) -> Finding:
    over = {k: round(v) for k, v in rss_mb.items() if v > MEMORY_MB}
    return Finding(not over, "warn", "Using too much memory: " + ", ".join(f"{k} {v} MB" for k, v in over.items())
                   + f" (over {MEMORY_MB:.0f} MB)", {"rss_mb": {k: round(v) for k, v in rss_mb.items()}})


def slow_render(seconds: float) -> Finding:
    return Finding(seconds <= SLOW_RENDER_S, "warn",
                   f"The dashboard took {seconds:.1f} s to render (over {SLOW_RENDER_S:.0f} s): a slow cache is being "
                   "rebuilt inside a page request", {"seconds": round(seconds, 2)})


def disk(free_gb: float) -> Finding:
    sev = "critical" if free_gb < DISK_CRITICAL_GB else "warn"
    return Finding(free_gb >= DISK_WARN_GB, sev, f"Only {free_gb:.1f} GB free on the data disk (marked under "
                   f"{DISK_WARN_GB:.0f} GB; critical under {DISK_CRITICAL_GB:.0f} GB)", {"free_gb": round(free_gb, 2)})


def clock(skew_s: float) -> Finding:
    return Finding(abs(skew_s) <= CLOCK_S, "warn",
                   f"The Mac's clock is {abs(skew_s):.0f} s {'fast' if skew_s > 0 else 'slow'}: System Settings → "
                   "General → Date & Time → set time automatically", {"skew_s": round(skew_s, 1)})


def sleep_setting(pmset_text: str) -> Finding:
    ac = pmset_text.split("AC Power:")[-1] if "AC Power:" in pmset_text else pmset_text
    m = re.search(r"^\s*sleep\s+(\d+)", ac, re.M)
    minutes = int(m.group(1)) if m else 0
    return Finding(minutes == 0, "warn",
                   f"The Mac sleeps after {minutes} min on mains power, which stops the recorders and stretches the "
                   f"nightly job. Run once in Terminal: {SLEEP_FIX}", {"ac_sleep_min": minutes})


def power_cut(uptime_min: float, missed_snapshot: bool) -> Finding:
    return Finding(not (uptime_min < 15 and missed_snapshot), "info",
                   f"The Mac restarted {uptime_min:.0f} min ago and a five-minute recording was missed: a power cut or "
                   "a crash. The catch-up runs on its own.", {"uptime_min": round(uptime_min, 1)})


def snapshot_missed(log_tail: list[str], now: datetime, session: bool) -> bool:
    """In a session, no snapshot line in the last ten minutes."""
    if not session:
        return False
    times = [m.group(1) for line in log_tail if (m := re.match(r"(\d\d:\d\d) ", line))]
    if not times:
        return True
    h, mi = map(int, times[-1].split(":"))
    return (now.hour * 60 + now.minute) - (h * 60 + mi) > 10


# --- repairs ---------------------------------------------------------------------------

def tidy_disk(data_dir: Path = DATA, limit_bytes: int = LOG_LIMIT) -> tuple[bool, str]:
    """Compress and empty any log over the limit. Never touches a database."""
    done, freed = [], 0
    for log in sorted(data_dir.glob("*.log")):
        size = log.stat().st_size
        if size <= limit_bytes:
            continue
        with open(log, "rb") as src, gzip.open(log.with_name(log.name + ".1.gz"), "wb") as dst:
            shutil.copyfileobj(src, dst)
        log.write_bytes(b"")
        done.append(log.name)
        freed += size
    return True, (f"compressed {len(done)} log(s), {freed / 1e6:.0f} MB" if done else "no log over the limit")


def _restart(key: str) -> tuple[bool, str]:
    from scripts.health_watch import restart
    return (True, f"{key} restarted") if restart(LABELS[key]) else (False, f"{key} restart failed")


def _restart_leaking() -> tuple[bool, str]:
    over = [k for k, v in rss_by_service(_ps()).items() if v > MEMORY_MB]
    results = [_restart(k) for k in over]
    return all(ok for ok, _ in results), "; ".join(m for _, m in results) or "nothing over the limit now"


register_repair("restart_api", lambda: _restart("api"), allow_in_session=True)
register_repair("restart_leaking", _restart_leaking)
register_repair("tidy_disk", tidy_disk)


# --- measuring -------------------------------------------------------------------------

def _get_seconds(url: str, timeout: float = 30) -> float:
    t = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            r.read()
    except Exception:
        return float("inf")
    return time.monotonic() - t


def _ps() -> str:
    return subprocess.run(["ps", "-axo", "rss=,command="], capture_output=True, text=True, timeout=10).stdout


def _skew() -> float:
    import requests  # brings its own certificates; python.org's Python has none of its own
    server = parsedate_to_datetime(requests.head("https://www.google.com", timeout=10).headers["Date"])
    return (datetime.now(timezone.utc) - server).total_seconds()


def _uptime_min() -> float:
    if sys.platform == "darwin":
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5).stdout
        return (time.time() - int(re.search(r"sec = (\d+)", out).group(1))) / 60
    return float(Path("/proc/uptime").read_text().split()[0]) / 60


def _power_cut() -> Finding:
    from market_data.kite_session import IST
    from sentinel.core import session_open
    now = datetime.now(IST)
    log = DATA / "snapshots.launchd.log"
    tail = log.read_text(errors="replace").splitlines()[-20:] if log.exists() else []
    return power_cut(_uptime_min(), snapshot_missed(tail, now, session_open(now)))


def _sleep() -> Finding:
    if sys.platform != "darwin":
        return Finding(True, "info", "not a Mac")
    return sleep_setting(subprocess.run(["pmset", "-g", "custom"], capture_output=True, text=True, timeout=10).stdout)


def machine_checks() -> list[Check]:
    return [
        Check("slow_api", "process", ("fast",), lambda: slow_api([_get_seconds(API_URL) for _ in range(5)]),
              "restart_api"),
        Check("memory", "process", ("fast",), lambda: memory(rss_by_service(_ps())), "restart_leaking"),
        # Two renders, the faster counts: the first after a restart fills cold caches and is slow by nature.
        Check("slow_render", "process", ("fast",), lambda: slow_render(min(_get_seconds(WEB_URL), _get_seconds(WEB_URL)))),
        Check("disk", "data", ("fast",), lambda: disk(shutil.disk_usage(DATA).free / 1e9), "tidy_disk"),
        Check("power_cut", "machine", ("fast",), _power_cut),
        Check("clock", "machine", ("deep",), lambda: clock(_skew())),
        Check("sleep_setting", "machine", ("deep",), _sleep),
    ]
