"""Run one evening of paper observation (Phase 14).

    cd api && .venv/bin/python scripts/paper_observe.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from briefing.paper import observe, report  # noqa: E402


def main() -> None:
    r = observe()
    print(f"entry session {r.get('entry_session')} (signal {r.get('signal_session')}): "
          f"opened {len(r['opened'])}, marked {r['marked']}, closed {len(r['closed'])}"
          + (f" — {r['note']}" if r.get("note") else ""))
    for name in r["opened"]:
        print(f"  opened  {name}")
    for name in r["closed"]:
        print(f"  closed  {name}")
    s = report()["summary"]
    print(f"patterns: {s['patterns']}")
    print(f"control:  {s['control']}")


if __name__ == "__main__":
    main()
