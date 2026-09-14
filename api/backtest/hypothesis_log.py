"""Append-only log of every strategy/parameter combination tested against
real data. This is the lightweight version of the project spec's
multiple-comparisons safeguard: before anything is called "validated," we
need an honest count of how many things were tried. A JSON file is enough
at this scale — a database would be premature until this needs querying
across many more runs than a personal project generates.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).parent / "hypothesis_log.json"


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
    existing = []
    if LOG_PATH.exists():
        existing = json.loads(LOG_PATH.read_text())
    existing.append(entry)
    LOG_PATH.write_text(json.dumps(existing, indent=2))


def total_hypotheses_tested() -> int:
    if not LOG_PATH.exists():
        return 0
    return len(json.loads(LOG_PATH.read_text()))
