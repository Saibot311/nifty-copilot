"""Deep audit of Phases 0-12 on real data. See audit/__init__.py.

    python scripts/audit.py                 # every phase
    python scripts/audit.py --phase 5 6     # just these
    python scripts/audit.py --live          # include checks that call external APIs

Exits non-zero if any check FAILs. Writes the full evidence to
data/audit_results.json.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import audit  # noqa: E402
import audit.checks  # noqa: E402,F401

OUT = Path(__file__).parent.parent / "data" / "audit_results.json"
COLOURS = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m", "SKIP": "\033[90m"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", nargs="*")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", help="print evidence for every check")
    args = ap.parse_args()

    results = audit.run(set(args.phase) if args.phase else None, live=args.live)
    OUT.write_text(json.dumps(results, indent=2, default=str))

    phase = None
    for r in results:
        if r["phase"] != phase:
            phase = r["phase"]
            print(f"\n\033[1m== Phase {phase} ==\033[0m")
        c = COLOURS[r["status"]]
        print(f"{c}{r['status']:4}\033[0m  {r['id']:5} {r['title']}  \033[90m({r['seconds']}s)\033[0m")
        print(f"             {r['summary']}")
        if (args.verbose or r["status"] in ("FAIL", "WARN")) and r["evidence"]:
            for k, v in r["evidence"].items():
                print(f"             \033[90m{k}: {json.dumps(v, default=str)[:300]}\033[0m")

    counts = {s: sum(1 for r in results if r["status"] == s) for s in COLOURS}
    print(f"\n\033[1m{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail, {counts['SKIP']} skipped\033[0m"
          f"  -> {OUT}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
