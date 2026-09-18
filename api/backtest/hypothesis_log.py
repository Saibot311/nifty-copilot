"""Append-only log of every strategy/parameter combination tested against
real data — the count behind the multiple-comparisons bar (I5).

Stored as JSON Lines: one entry per line, appended under an OS file lock.
It used to be one JSON array rewritten in full on every call, which broke
twice: first under concurrent threads (fixed with a thread lock), then
across processes — the API server and a research script both rewriting a
4.8 MB file, one reading it in the instant the other had truncated it.
Appending a line never rewrites what's already there, and the file lock
covers every process, not just threads in one.
"""

import fcntl
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent / "hypothesis_log.jsonl"

_LOCK = threading.Lock()


def log_run(strategy_name: str, params: dict, symbol: str, days: int, metrics: dict) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_name,
        "params": params,
        "symbol": symbol,
        "lookback_days": days,
        "num_trades": metrics.get("num_trades"),
        "expectancy_pct": metrics.get("expectancy_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
    }
    line = json.dumps(entry) + "\n"
    with _LOCK, open(LOG_PATH, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _read() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    with open(LOG_PATH) as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return [json.loads(line) for line in f if line.strip()]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def total_hypotheses_tested() -> int:
    """Number of *distinct* strategy+parameter combinations ever tested.

    Deliberately not the raw row count. Every dashboard load re-runs several
    backtests, and each one appends a row — but re-measuring a strategy that
    was already tested is not a new hypothesis, and counting it as one made
    the multiple-comparisons bar climb purely from using the app (6,342
    logged runs were only 86 distinct hypotheses; the bar had inflated from
    ~0.49% to 0.725% expectancy with no new research behind it).
    """
    with _LOCK:
        entries = _read()
    return len({(e.get("strategy"), json.dumps(e.get("params"), sort_keys=True)) for e in entries})


def total_runs_logged() -> int:
    """Raw row count, including repeats — kept for transparency so the
    distinct-vs-total gap is inspectable rather than hidden."""
    with _LOCK:
        return len(_read())
