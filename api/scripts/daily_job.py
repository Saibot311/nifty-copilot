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
7. Tops up NSE's participant-wise open interest and re-runs the market
   context engine's studies.

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


def notify(message: str) -> None:
    """A macOS notification — the nightly job runs unattended, and a failure
    nobody sees is the same as no check at all. Best effort: never fails the job."""
    safe = message.replace('"', "'")[:220]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "NIFTY Copilot"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def step_gift_nifty() -> bool:
    from market_data.gift_nifty import fetch
    from storage.gift_nifty_db import count, save

    q = fetch()
    if q is None:
        log("    no traded near-month contract")
        return True
    save(q)
    log(f"    {q['symbol']} {q['last']} ({q['change_pct']}%) at {q['last_trade_time']}; {count()} snapshots")
    return True


def step_paper() -> bool:
    """Phase 14: open, mark and close the paper positions for today. Runs
    after the options archive so the entry session's premiums exist."""
    from briefing.paper import observe

    r = observe()
    log(f"    entry session {r.get('entry_session')}: opened {len(r['opened'])}, marked {r['marked']}, "
        f"closed {len(r['closed'])}" + (f" — {r['note']}" if r.get("note") else ""))
    for name in r["opened"] + r["closed"]:
        log(f"      {name}")
    return True


def step_audit() -> bool:
    """The phase-by-phase audit on real data, after everything is refreshed.
    Every bug the audit ever found had hidden for a while unnoticed."""
    import json

    ok = run_script("scripts/audit.py")
    try:
        results = json.loads((API_DIR / "data" / "audit_results.json").read_text())
        rows = results if isinstance(results, list) else []
        failed = [r.get("id") for r in rows if r.get("status") == "FAIL"]
    except Exception:
        failed = []
    if not ok or failed:
        notify(f"Nightly audit FAILED: {', '.join(map(str, failed)) or 'see daily_job.log'}")
    return ok


def step_backup() -> bool:
    from storage.backup import backup_forward_log, backup_news

    from storage.backup import backup_journal, backup_paper

    ok = True
    for r in (backup_forward_log(), backup_journal(), backup_paper(), backup_news()):
        log(f"    {r['summary']}")
        ok = ok and r["ok"]
    return ok


def step_options() -> bool:
    # Both passes always run: a failed recent day is exactly when filling
    # older gaps still matters, so one must not short-circuit the other.
    recent = run_script("scripts/backfill_options.py", "--start", str(date.today() - timedelta(days=10)))
    gaps = run_script("scripts/backfill_options.py", "--fill-gaps")
    return recent and gaps


def step_login_record() -> bool:
    """Record whether today had a Zerodha session. Never prompts at 19:30 —
    the market is shut and a login then is worth nothing."""
    return run_script("scripts/kite_login.py", "--check-only")


def _tone_from() -> str:
    """Only re-fetch the recent window: the archive already holds the rest,
    and GDELT answers 429 to anyone who asks for eight years nightly."""
    from datetime import date, timedelta

    return (date.today() - timedelta(days=45)).isoformat()


def step_news() -> bool:
    """Pull every feed, store what is new, and send the newest unjudged
    headlines to Jev. Judging is best-effort: the archive is the part that
    cannot be rebuilt later, and a judgment can always be added afterwards."""
    from news.feed import JUDGE_NIGHTLY, refresh

    out = refresh(judge=JUDGE_NIGHTLY)
    log(f"    {out['new']} new of {out['fetched']} fetched, {out['judged']} judged")
    if out.get("failed"):
        log(f"    sources that failed: {', '.join(out['failed'])}")
    if out.get("judge_error"):
        log(f"    judging: {out['judge_error']}")
    return True


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
        ("forward log, journal and paper backup", step_backup),
        # Before the forward log: NSE's index report carries today's close
        # when Yahoo does not have it yet.
        ("NSE index report", lambda: run_script("scripts/backfill_nse_indices.py", "--recent")),
        ("forward log", step_forward_log),
        ("Zerodha session record", step_login_record),
        ("kite bars", step_kite_bars),
        ("options archive", step_options),
        ("other index options", lambda: run_script("scripts/backfill_other_indices.py", "--recent")),
        ("pattern -> option research", lambda: run_script("scripts/pattern_options.py")),
        ("implied volatility", lambda: run_script("scripts/iv_research.py")),
        ("participant positioning", lambda: run_script("scripts/backfill_participant_oi.py")),
        # After positioning: two of the six read today's participant file.
        ("structural hypotheses", lambda: run_script("scripts/structural_research.py")),
        ("replication on other indices", lambda: run_script("scripts/replication.py")),
        # News before the paper book, like the other research: the book ranks
        # a news signal by that study's holdout t and reads its signals off
        # the tone series, so both have to be current when it decides.
        ("news archive and judging", step_news),
        ("news tone series", lambda: run_script("scripts/backfill_news_tone.py", "--from", _tone_from())),
        ("news hypotheses", lambda: run_script("scripts/news_research.py")),
        ("paper observation", step_paper),
        ("market context studies", lambda: run_script("scripts/market_research.py")),
        ("GIFT Nifty snapshot", step_gift_nifty),
        ("audit", step_audit),
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
    if failed and failed != ["audit"]:  # the audit step sends its own alert
        notify(f"Nightly job: {', '.join(failed)} failed — see api/data/daily_job.log")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
