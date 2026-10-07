"""Data and backup checks (spec §3.2: D2, D3, D4, B1, B2).

Nothing here writes to an irreplaceable database: integrity and restore
tests open copies or open read-only, and a corrupt database is reported,
never repaired — restoring one is the owner's decision."""

import re
import shutil
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

from sentinel.core import Check, Finding, register_repair

DATA = Path(__file__).parent.parent / "data"
WAL_LIMIT = 200 * 1024 * 1024
BACKUP_MAX_AGE = timedelta(days=2)
RESTORE_EVERY = timedelta(days=30)

# (backup stem, live database, its main table): the list B1, B2 and D2 read.
IRREPLACEABLE = (
    ("forward_log", DATA / "forward_log.db", "recommendation_log"),
    ("journal", DATA / "journal.db", "journal"),
    ("paper", DATA / "paper.db", "paper_trades"),
    ("news", DATA / "news.db", "headlines"),
    ("gift_nifty", DATA / "gift_nifty.db", "snapshots"),
    ("option_snapshots", DATA / "option_snapshots.db", "snapshots"),
    ("intraday_forward", DATA / "intraday_forward.db", "events"),
    ("day_forecast", DATA / "day_forecast.db", "forecasts"),
    ("breakouts", DATA / "breakouts.db", "events"),
    ("incidents", DATA / "incidents.db", "incidents"),
)
ARCHIVES = (DATA / "nifty_bars.db", DATA / "nifty_options.db", DATA / "nse_indices.db", DATA / "iv.db")


# --- pure checks ---------------------------------------------------------------------

def _quick_check(path: Path) -> str:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            return conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return str(e)


def integrity(paths: list[Path]) -> Finding:
    bad = {p.name: r for p in paths if p.exists() and (r := _quick_check(p)) != "ok"}
    return Finding(not bad, "critical",
                   "Database damaged: " + ", ".join(bad) + ". Restoring from a backup needs you; nothing was changed.",
                   {"results": bad})


def wal_sizes(paths: list[Path], limit_bytes: int = WAL_LIMIT) -> Finding:
    big = {p.name: (p.parent / (p.name + "-wal")).stat().st_size for p in paths
           if (p.parent / (p.name + "-wal")).exists() and (p.parent / (p.name + "-wal")).stat().st_size > limit_bytes}
    return Finding(not big, "warn", "Write-ahead log oversized: " + ", ".join(f"{k} {v / 1e6:.0f} MB" for k, v in big.items()),
                   {"wal_bytes": big})


def gaps(archived: dict[str, set[str]], sessions: list[date]) -> Finding:
    missing = {tf: [d.isoformat() for d in sessions if d.isoformat() not in days] for tf, days in archived.items()}
    missing = {tf: m for tf, m in missing.items() if m}
    return Finding(not missing, "warn",
                   "Sessions missing from the bar archive: " + "; ".join(f"{tf} {', '.join(m)}" for tf, m in missing.items())
                   + " (a lapsed Kite login is the usual cause)", {"missing": missing})


def _weekdays_before(today: date, n: int) -> date:
    d = today
    for _ in range(n):
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def backups_fresh(newest: dict[str, date | None], today: date) -> Finding:
    """The job backs up on weekdays: a backup is stale when it is older than the
    second weekday before today (one missed night allowed; Friday's is fresh on
    Monday morning)."""
    oldest_ok = _weekdays_before(today, 2)
    stale = {s: (d.isoformat() if d else None) for s, d in newest.items() if d is None or d < oldest_ok}
    return Finding(not stale, "warn", "Backup missing or older than two weekdays: "
                   + ", ".join(f"{s} ({d or 'none'})" for s, d in stale.items()), {"stale": stale})


def _rows(path: Path, table: str) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def restore_test(backup: Path, live: Path, table: str) -> Finding:
    """Copy the backup aside, check it, count its rows: it may trail the live
    database (written since), never lead it."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / backup.name
        shutil.copy2(backup, copy)
        check = _quick_check(copy)
        try:
            n_backup, n_live = _rows(copy, table), _rows(live, table)
        except sqlite3.Error as e:
            return Finding(False, "critical", f"Backup {backup.name} does not restore: {e}")
    ok = check == "ok" and n_backup <= n_live
    return Finding(ok, "critical", f"Backup {backup.name} does not restore cleanly: check {check!r}, "
                   f"{n_backup} rows against {n_live} live", {"rows_backup": n_backup, "rows_live": n_live})


# --- repairs ---------------------------------------------------------------------------

def checkpoint_wal(paths: list[Path]) -> tuple[bool, str]:
    done = []
    for p in paths:
        if (p.parent / (p.name + "-wal")).exists():
            conn = sqlite3.connect(p, timeout=30)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                done.append(p.name)
            finally:
                conn.close()
    return True, "checkpointed " + (", ".join(done) or "nothing")


def _run_backup() -> tuple[bool, str]:
    import importlib.util
    spec = importlib.util.spec_from_file_location("daily_job", Path(__file__).parent.parent / "scripts" / "daily_job.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    return (True, "backups taken") if job.step_backup() else (False, "a backup failed verification")


def _fill_gaps() -> tuple[bool, str]:
    import subprocess
    import sys
    api = Path(__file__).parent.parent
    ok = all(subprocess.run([sys.executable, "scripts/backfill_bars.py", "--timeframe", tf], cwd=api,
                            capture_output=True, timeout=1800).returncode == 0 for tf in ("1d", "5m"))
    return ok, "bars backfilled" if ok else "backfill failed (is the Kite login current?)"


register_repair("checkpoint_wal", lambda: checkpoint_wal([p for _, p, _ in IRREPLACEABLE] + list(ARCHIVES)))
register_repair("run_backup", _run_backup)
register_repair("fill_bar_gaps", _fill_gaps)


# --- measuring -------------------------------------------------------------------------

def backup_dir() -> Path:
    """Where storage/backup.py writes: BACKUP_DIR in api/.env, else api/data/backups."""
    from storage.backup import DEFAULT_DIR, _env
    return Path(_env("BACKUP_DIR") or DEFAULT_DIR).expanduser()


def newest_backups(dest: Path | None = None) -> dict[str, date | None]:
    dest = dest or backup_dir()
    out: dict[str, date | None] = {}
    for stem, _, _ in IRREPLACEABLE:
        dates = [date.fromisoformat(m.group(1)) for f in dest.glob(f"{stem}-*.db")
                 if (m := re.fullmatch(rf"{stem}-(\d{{4}}-\d\d-\d\d)\.db", f.name))]
        out[stem] = max(dates) if dates else None
    return out


def _sessions(days: int = 30) -> list[date]:
    """Sessions in the last `days` before today whose nightly top-up has run."""
    from market_data.nse_holidays import is_session, trading_holidays
    hol, _ = trading_holidays()
    today = date.today()
    return [d for k in range(days, 0, -1) if is_session(d := today - timedelta(days=k), hol)]


def _archived() -> dict[str, set[str]]:
    conn = sqlite3.connect(f"file:{DATA / 'nifty_bars.db'}?mode=ro", uri=True)
    try:
        since = (date.today() - timedelta(days=40)).isoformat()
        return {tf: {r[0] for r in conn.execute(
            "SELECT DISTINCT substr(ts, 1, 10) FROM index_bars WHERE symbol = '^NSEI' AND interval = ? AND ts >= ?",
            (tf, since))} for tf in ("1d", "5m")}
    finally:
        conn.close()


RESTORE_STATE = DATA / "sentinel_restore.json"


def _restore_monthly() -> Finding:
    import json
    try:
        state = json.loads(RESTORE_STATE.read_text())
    except (OSError, ValueError):
        state = {}
    last = state.get("restore_tested_on")
    if last and date.today() - date.fromisoformat(last) < RESTORE_EVERY:
        return Finding(True, "info", "restore tested on " + last)
    newest = newest_backups()
    for stem, live, table in IRREPLACEABLE:
        if newest.get(stem) and live.exists():
            f = restore_test(backup_dir() / f"{stem}-{newest[stem].isoformat()}.db", live, table)
            if not f.ok:
                return f
    state["restore_tested_on"] = date.today().isoformat()
    RESTORE_STATE.write_text(json.dumps(state, indent=1))
    return Finding(True, "info", "every newest backup restored and counted")


def data_checks() -> list[Check]:
    live = [p for _, p, _ in IRREPLACEABLE]
    return [
        Check("integrity", "data", ("deep",), lambda: integrity(live + list(ARCHIVES))),
        Check("wal_size", "data", ("fast",), lambda: wal_sizes(live + list(ARCHIVES)), "checkpoint_wal"),
        Check("bar_gaps", "data", ("deep",), lambda: gaps(_archived(), _sessions()), "fill_bar_gaps"),
        Check("backups_fresh", "backups", ("fast",), lambda: backups_fresh(newest_backups(), date.today()),
              "run_backup"),
        Check("restore_test", "backups", ("deep",), _restore_monthly),
    ]
