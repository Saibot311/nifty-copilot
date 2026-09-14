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


def total_hypotheses_tested() -> int:
    with _LOCK:
        if not LOG_PATH.exists():
            return 0
        return len(json.loads(LOG_PATH.read_text()))
