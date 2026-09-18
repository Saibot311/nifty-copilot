"""Append-only log of every strategy/parameter combination tested against
real data. This is the lightweight version of the project spec's
multiple-comparisons safeguard: before anything is called "validated," we
need an honest count of how many things were tried. A JSON file is enough
at this scale — a database would be premature until this needs querying
across many more runs than a personal project generates.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent / "hypothesis_log.json"

# The dashboard fires several API requests at once, more than one of which
# calls log_run(). Without a lock, two threads can each read the file,
# append their own entry in memory, and write back — the second write
# lands on top of the first with no error, and whichever write is shorter
# leaves trailing bytes from the other, corrupting the JSON for every
# reader afterwards ("Extra data" parse errors). A lock around the whole
# read-modify-write makes each log_run() call atomic relative to the others.
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
    with _LOCK:
        existing = []
        if LOG_PATH.exists():
            existing = json.loads(LOG_PATH.read_text())
        existing.append(entry)
        LOG_PATH.write_text(json.dumps(existing, indent=2))


def _read() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    return json.loads(LOG_PATH.read_text())


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
