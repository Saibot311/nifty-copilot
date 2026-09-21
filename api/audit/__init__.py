"""Deep audit: every phase checked against real data, systematically.

The unit tests in tests/ prove each piece does what its author meant, on
inputs its author chose. This is a different question: on the data this
system actually runs on, does each phase do what it claims? A test suite
cannot find the bug its author did not imagine; an audit that recomputes
things independently sometimes can.

Three rules for every check here:
  1. Real data, not fixtures. Mocks are what tests/ is for.
  2. Where possible, an independent reference implementation — recomputing
     a value with the same code only proves the code agrees with itself.
  3. Measure the impact, not just the existence. "Bands 2.6% wider" means
     nothing until it says how many signals it changed.

    python scripts/audit.py               # everything
    python scripts/audit.py --phase 5     # one phase
    python scripts/audit.py --live        # include checks that call paid APIs

Checks register themselves with @check; importing audit.checks loads them all.
"""

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"


@dataclass
class Result:
    status: str
    summary: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Check:
    phase: str
    id: str
    title: str
    fn: Callable[[], Result]
    live: bool = False  # calls a paid or rate-limited external API


REGISTRY: list[Check] = []


def check(phase: str, id: str, title: str, live: bool = False):
    def wrap(fn):
        REGISTRY.append(Check(phase, id, title, fn, live))
        return fn
    return wrap


def run(phases: set[str] | None = None, live: bool = False) -> list[dict]:
    out = []
    for c in REGISTRY:
        if phases and c.phase not in phases:
            continue
        if c.live and not live:
            out.append({"phase": c.phase, "id": c.id, "title": c.title, "status": SKIP,
                        "summary": "calls an external API — run with --live", "evidence": {}, "seconds": 0})
            continue
        t0 = time.time()
        try:
            r = c.fn()
        except Exception as e:
            # A check that crashes is a finding, not a skipped check.
            r = Result(FAIL, f"check raised {type(e).__name__}: {e}",
                       {"traceback": traceback.format_exc().splitlines()[-6:]})
        out.append({"phase": c.phase, "id": c.id, "title": c.title, "status": r.status,
                    "summary": r.summary, "evidence": r.evidence, "seconds": round(time.time() - t0, 1)})
    return out
