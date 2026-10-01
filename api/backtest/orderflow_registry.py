"""Four order-flow hypotheses on the five-minute option snapshots, registered
for a FORWARD test: judged only on sessions recorded after registration.

The snapshots begin on 1 Oct 2026 and nothing earlier exists, so there is no
development period and no holdout to look back on. Each rule is fixed here,
fingerprinted, and then left alone: backtest/orderflow_forward.py runs it on
every session from 2 Oct 2026 and refuses to judge until the registered
minimums are met, closing the sample at the session they are first reached,
so the verdict cannot be taken at a lucky moment.

Registered on the owner's instruction ("do everything", 1 Oct 2026) after the
drafts in docs/research/orderflow-candidates.md. All four together put the
family at 69; each is judged at that bar. The drafts' own expectation, kept
here: every one of them most likely fails, and C and D need a year or more of
recording before they can.
"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .orderflow_forward import ForwardSpec, Rule, evaluate

API_DIR = Path(__file__).parent.parent
RESULT_PATH = API_DIR / "data" / "orderflow_forward.json"

PREREGISTERED = {
    "registered": "2026-10-01, after the session closed, before any rule below had been run on any session",
    "judged_on": "sessions from 2026-10-02 on, recorded after this registration",
    "source": "Drafted 2026-10-01 (docs/research/orderflow-candidates.md); registered on the owner's instruction.",
    "already_seen": (
        "On 1 Oct 2026, before registering: the features were computed on the first 13 snapshots of the 6 Oct "
        "expiry (09:18-10:49) to check they run; no rule outcome was computed. That morning showed ATM spreads of "
        "0.07-0.29% of mid, NSE's call and put IVs at one strike 2-3 points apart at 09:18 and under half a point "
        "by 10:49 (why B uses only the change), and the measured half-spreads by expiry and moneyness (Phase 1 at "
        "real spreads). The intraday rules' forward record and the five pipeline verdicts were also known. "
        "1 Oct itself is not in any judged sample."),
    "instrument": ("The pipeline's Phase 1 contract: the nearest expiry not expiring that day, at the money (the "
                   "deciding snapshot's spot rounded to 50); D buys the next expiry's, the one not expiring that day."),
    "prices": ("Bought at the ask in the first snapshot of that contract at least 60 s after the deciding snapshot; "
               "sold at the bid in the first snapshot at or after the exit time; a leg priced more than 360 s late "
               "is not counted. Rate-card costs, no assumed slippage (the spread is paid)."),
    "baseline": "The same contract bought and sold at the same clock times on every session from 2026-10-02 on.",
    "verdict": ("APPROVED only if the mean net return is positive, above the baseline's, and its t against the "
                "baseline clears the Bonferroni bar for 69 hypotheses at its own degrees of freedom, on the sample "
                "closed when both minimums are first met."),
    "hypotheses": {
        "oi_flow_writers": {
            "label": "Open-interest build-up (follow the writers)",
            "rule": ("At the first snapshot of the traded expiry stamped 11:00-11:10, with the session's first "
                     "snapshot by 09:30: oi_flow_open = ((put OI change since the open) - (call OI change since the "
                     "open)) / (call + put OI at the open), over strikes within 2% of spot. > 0 buys the ATM call, "
                     "< 0 the ATM put, 0 or missing no trade. Out at 15:25."),
            "source": "Pan & Poteshman (2006, RFS 19(3)); fresh OI read as writing by the better-informed side.",
            "min_sessions": 330, "min_trades": 330,
        },
        "vol_spread_change": {
            "label": "Call-put volatility spread change",
            "rule": ("At the first snapshot stamped 11:00-11:10, with an open by 09:30: vol_spread_chg_open = the "
                     "change since the session's first snapshot in (call IV - put IV) averaged over the three "
                     "strikes nearest spot. > 0 buys the ATM call, < 0 the ATM put. Out at 15:25."),
            "source": "Cremers & Weinbaum (2010, JFQA 45(2)); An, Ang, Bali & Cakici (2014, JF 69(5)).",
            "min_sessions": 330, "min_trades": 330,
        },
        "book_pressure_30m": {
            "label": "Order-book pressure, 30 minutes",
            "rule": ("At the first snapshot stamped 11:00-11:10: the average, over the snapshots of the 30 minutes "
                     "up to and including it (at least 5), of near-call imbalance minus near-put imbalance, each "
                     "(sum bid qty - sum ask qty) / (sum bid qty + sum ask qty) over the ATM strike and two either "
                     "side. > 0 buys the ATM call, < 0 the ATM put. Out at the first snapshot 30 minutes after the "
                     "deciding one."),
            "source": "Cont, Kukanov & Stoikov (2014, JFEc 12(1)); Muravyev (2016, JF 71(2)). The weakest prior.",
            "min_sessions": 250, "min_trades": 250,
        },
        "expiry_pin": {
            "label": "Expiry-day pull to the largest-OI strike",
            "rule": ("Only on the nearest listed series' expiry day, at its first snapshot stamped 13:00-13:10: the "
                     "strike with the largest call + put OI within 2% of spot. Spot at least 0.25% above it buys "
                     "the put, at least 0.25% below it the call, of the next expiry's ATM contract. Out at 15:25."),
            "source": "Ni, Pearson & Poteshman (2005, JFE 78(1)); Golez & Jackwerth (2012, JFE 106(3)); largest-OI "
                      "strike in place of the ATM strike has no published backing.",
            "min_sessions": 620, "min_trades": 62,
        },
    },
    "sizing": ("Minimums from orderflow_forward.trades_needed at 69 tests with return spreads estimated from the "
               "pipeline's modelled options (46% of premium for a 4-hour hold, 20% for 30 minutes): the trades a "
               "10 pp edge (A, B), a 5 pp edge (C) or a 20 pp edge (D) needs. Smaller real edges will not be found."),
}
TESTS_IN_FAMILY = 69
REGISTERED_ON = date(2026, 10, 2)
ENTRY_DELAY_S, MAX_LATE_S = 60, 360
PREREG_HASH = "57c29550776a8810"


def _first_at_or_after(hist: list[dict], clock: time) -> bool:
    t = datetime.fromisoformat(hist[-1]["taken_at"]).time()
    prev = datetime.fromisoformat(hist[-2]["taken_at"]).time() if len(hist) > 1 else None
    return t >= clock and (prev is None or prev < clock)


def _sign(x) -> int | None:
    return None if x is None or x == 0 else (1 if x > 0 else -1)


def oi_flow_decide(hist, _bars):
    if not _first_at_or_after(hist, time(11, 0)) or not hist[-1]["open_ok"]:
        return None
    return _sign(hist[-1]["oi_flow_open"])


def vol_spread_decide(hist, _bars):
    if not _first_at_or_after(hist, time(11, 0)) or not hist[-1]["open_ok"]:
        return None
    return _sign(hist[-1]["vol_spread_chg_open"])


def book_decide(hist, _bars):
    if not _first_at_or_after(hist, time(11, 0)):
        return None
    t = datetime.fromisoformat(hist[-1]["taken_at"])
    vals = [h["near_call_imbalance"] - h["near_put_imbalance"] for h in hist
            if datetime.fromisoformat(h["taken_at"]) >= t - timedelta(minutes=30)
            and h["near_call_imbalance"] is not None and h["near_put_imbalance"] is not None]
    if len(vals) < 5:
        return None
    return _sign(sum(vals) / len(vals))


def pin_decide(hist, _bars):
    f = hist[-1]
    if f["days_to_expiry"] != 0 or not _first_at_or_after(hist, time(13, 0)) or f["max_oi_dist_pct"] is None:
        return None
    if f["max_oi_dist_pct"] >= 0.25:
        return -1
    if f["max_oi_dist_pct"] <= -0.25:
        return 1
    return None


RULES = {
    "oi_flow_writers": Rule("oi_flow_writers", oi_flow_decide, first_check=time(11, 0), last_entry=time(11, 10)),
    "vol_spread_change": Rule("vol_spread_change", vol_spread_decide, first_check=time(11, 0), last_entry=time(11, 10)),
    "book_pressure_30m": Rule("book_pressure_30m", book_decide, first_check=time(11, 0), last_entry=time(11, 10),
                              hold_minutes=30),
    "expiry_pin": Rule("expiry_pin", pin_decide, first_check=time(13, 0), last_entry=time(13, 10),
                       features_on="nearest"),
}


def spec(name: str) -> ForwardSpec:
    h = PREREGISTERED["hypotheses"][name]
    return ForwardSpec(registered_on=REGISTERED_ON, tests_in_family=TESTS_IN_FAMILY, min_sessions=h["min_sessions"],
                       min_trades=h["min_trades"], entry_delay_s=ENTRY_DELAY_S, max_late_s=MAX_LATE_S)


def run_orderflow_forward(db_path: Path | None = None, result_path: Path | None = None) -> dict:
    """Every rule run on the sessions so far; each judged once its minimums are
    met (and logged then, once), otherwise reported as waiting."""
    from .hypothesis_log import log_run
    path = result_path or RESULT_PATH
    before = load_orderflow_forward(path) or {}
    judged_before = {h["name"] for h in before.get("hypotheses", []) if h.get("status") == "judged"}
    rows = []
    for name, rule in RULES.items():
        r = evaluate(rule, spec(name), db_path)
        trades = r.pop("trades")
        r.update(name=name, label=PREREGISTERED["hypotheses"][name]["label"], recorded=len(trades),
                 last_trades=trades[-5:])
        rows.append(r)
        if r.get("status") == "judged" and name not in judged_before:
            log_run(f"orderflow_{name}", {"prereg": PREREG_HASH, "forward": True}, "^NSEI", 0,
                    {"num_trades": r.get("num_trades"), "expectancy_pct": r.get("mean_pct")})
    out = {"computed_at": datetime.now().isoformat(timespec="seconds"), "prereg_hash": PREREG_HASH,
           "registered_on": REGISTERED_ON.isoformat(), "tests_in_family": TESTS_IN_FAMILY, "hypotheses": rows,
           "preregistered": PREREGISTERED}
    path.write_text(json.dumps(out, default=str))
    return out


def load_orderflow_forward(path: Path | None = None) -> dict | None:
    p = path or RESULT_PATH
    return json.loads(p.read_text()) if p.exists() else None


def judged_count() -> int:
    """Hypotheses here that have had their one look (for backtest/family.py)."""
    data = load_orderflow_forward() or {}
    return sum(1 for h in data.get("hypotheses", []) if h.get("status") == "judged")
