"""The market context engine: what is going on, who is on the other side,
and what the research says — for decisions and for understanding, never as
a trade signal.

Two layers:
  studies  slow, historical, saved nightly by scripts/market_research.py:
           the variance risk premium, how much global cues explain by year,
           the expiry-day footprint studies, positioning history.
  today    the latest session: why it moved, options' price against what
           the index has delivered, expiry flags, unusual strike activity,
           positioning now.

Nothing here predicts. Each part says what it is — attribution by
association, a statistic about the past, a description — and the one rule
of the rest of the system holds: every number comes from Python, from data.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import drivers, expiry, positioning, who_wins
from .knowledge import KNOWLEDGE

STUDIES_PATH = Path(__file__).parent.parent / "data" / "market_research.json"


def run_studies() -> dict:
    frame = drivers.load_frame()
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "variance_risk_premium": who_wins.variance_risk_premium(),
        "option_buyers_without_a_signal": who_wins.buyers_without_a_signal(),
        "global_cues_by_year": drivers.explanatory_power_by_year(frame),
        "expiry_footprints": expiry.study(),
        "positioning_history": positioning.history_summary(),
        "sebi": who_wins.SEBI_FACTS,
    }


def load_studies() -> dict | None:
    return json.loads(STUDIES_PATH.read_text()) if STUDIES_PATH.exists() else None


def today() -> dict:
    studies = load_studies() or {}
    return {
        "why_it_moved": drivers.attribute(drivers.load_frame()),
        "options_price_now": (studies.get("variance_risk_premium") or {}).get("now"),
        "expiry": expiry.latest_session_flags(),
        "unusual_strike_activity": expiry.unusual_option_activity(),
        "positioning": positioning.latest(),
    }


def market_context() -> dict:
    return {"today": today(), "studies": load_studies(), "knowledge": KNOWLEDGE}
