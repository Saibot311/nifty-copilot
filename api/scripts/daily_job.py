"""Daily after-close job: keeps the evidence accruing without anyone
remembering to open the dashboard.

    python scripts/daily_job.py

1. Backs up the forward log — the one file that cannot be regenerated.
2. Records today's recommendation in the forward log (only once the day's
   bar is final; write-once, so re-running is harmless).
3. Tops up the Kite 15-minute and daily bar archives — only if today's Zerodha
   login is still valid; otherwise skipped and said so (login needs a human).
   Runs before the options step: the index archive is what tells the options
   backfill which days were sessions.
4. Tops up the NSE options archive (bhavcopy, free, no login): the last ten
   days, then any session since 2018 still missing data.
5. Recomputes pattern -> option research so verdicts include the newest data.
6. Extends the implied-volatility series and re-runs its description and the
   pre-registered filter test (the hypothesis is fixed; only the data grows).

Each step runs independently: one failing doesn't stop the others. Output is
appended to data/daily_job.log. Scheduled by a macOS LaunchAgent at 19:30 IST
on weekdays (see scripts/install_daily_job.sh).
"""

import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

API_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(API_DIR))

LOG = API_DIR / "data" / "daily_job.log"


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run_script(*args: str) -> bool:
    proc = subprocess.run([sys.executable, *args], cwd=API_DIR, capture_output=True, text=True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    for t in tail:
        log(f"    {t}")
    return proc.returncode == 0


def step_forward_log() -> bool:
    from briefing.forward_log import record_if_final
    from briefing.recommendation import build_recommendation

    rec = build_recommendation()
    written = record_if_final(rec)
    log(f"    {rec['as_of']}: {rec['action']} — {'recorded' if written else 'already recorded or bar not final'}")
    return True


def step_backup() -> bool:
    from storage.backup import backup_forward_log

    r = backup_forward_log()
    log(f"    {r['summary']}")
    return r["ok"]


def step_options() -> bool:
    # Both passes always run: a failed recent day is exactly when filling
    # older gaps still matters, so one must not short-circuit the other.
    recent = run_script("scripts/backfill_options.py", "--start", str(date.today() - timedelta(days=10)))
    gaps = run_script("scripts/backfill_options.py", "--fill-gaps")
    return recent and gaps


def step_kite_bars() -> bool:
    from market_data.kite_session import session_status

    status = session_status()
    if not status["logged_in"]:
        log(f"    skipped: {status['reason']}")
        return True
    return run_script("scripts/backfill_bars.py", "--timeframe", "15m") and run_script(
        "scripts/backfill_bars.py", "--timeframe", "1d"
    )


def main() -> int:
    log("daily job start")
    steps = [
        ("forward log backup", step_backup),
        ("forward log", step_forward_log),
        ("kite bars", step_kite_bars),
        ("options archive", step_options),
        ("pattern -> option research", lambda: run_script("scripts/pattern_options.py")),
        ("implied volatility", lambda: run_script("scripts/iv_research.py")),
    ]
    failed = []
    for name, fn in steps:
        log(f"  {name}")
        try:
            if not fn():
                failed.append(name)
        except Exception:
            failed.append(name)
            log("    " + traceback.format_exc().strip().replace("\n", "\n    "))
    log(f"daily job done{' — FAILED: ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
