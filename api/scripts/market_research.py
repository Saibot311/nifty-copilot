"""The market context engine's historical studies, saved for the API.

    python scripts/market_research.py

Variance risk premium, global cues' explanatory power by year, the
expiry-day footprint studies, and positioning history. See market_engine/.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_engine.engine import STUDIES_PATH, run_studies  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    s = run_studies()
    STUDIES_PATH.write_text(json.dumps(s, indent=2, default=str))
    v = s["variance_risk_premium"]
    print(f"saved in {time.time() - t0:.0f}s -> {STUDIES_PATH}")
    print(f"options priced above what followed on {v['options_overpriced_share']:.0%} of {v['days']} days "
          f"(median gap {v['median_gap_points']} vol points)")
    e = s["expiry_footprints"]["all"]
    print(f"expiry footprints: reversal z={e['reversal']['z']}, settlement window t={e['settlement_window']['t']}, "
          f"pinning z={e['pinning']['z']}")
