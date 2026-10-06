"""Which way the day-ahead forecast sizes its band, chosen from its own record.

The forecast's width has always been recalibrated nightly (day_forecast's k).
This goes one step further and lets the method itself change, by a stated
rule, the same every night:

  iv          the 30-day implied volatility on the market clock (the original)
  iv_rv_blend half implied, half what NIFTY actually moved over the last
              RV_WINDOW sessions: catches a regime IV is slow to price
  iv_weekday  implied, widened or narrowed by how each weekday's moves have
              run against it over the last WEEKDAY_WINDOW sessions

Each method's width for a day uses only sessions before it, and is
calibrated by its own k exactly as the forecast is. They are scored by the
log likelihood of the close under each band (a proper score: it rewards a
band that is right-sized, not merely wide), over the last TRIAL sessions. A
challenger replaces the method in use only when it scores at least MARGIN
higher per session over the trial and higher in each half of it — so one
lucky stretch cannot flip the method. Every night's choice is recorded,
never edited (storage/day_forecast_db.method_choices).

Only the width learns. The lean stays a base rate: nothing here has called
NIFTY's direction better than chance, and a direction that tuned itself on
its own record would mostly learn noise.
"""

import math
import statistics

from .day_forecast import CAL_WINDOW, K_BOUNDS, _clip, units_between

METHODS = ("iv", "iv_rv_blend", "iv_weekday")
LABELS = {"iv": "implied volatility",
          "iv_rv_blend": "implied and recent realised volatility, half each",
          "iv_weekday": "implied volatility, adjusted by weekday"}
TRIAL = 250          # sessions the methods are compared on, the most recent
MARGIN = 0.02        # mean log score per session a challenger must win by
K_MIN = 20           # sessions of a method's own errors before it is scored
RV_WINDOW = 20
WEEKDAY_WINDOW = 250
WEEKDAY_MIN = 30


def _rms(xs: list[float]) -> float:
    return math.sqrt(statistics.mean(x * x for x in xs))


def raw_sigmas(rows: list[dict]) -> dict[str, list[float | None]]:
    """Each method's width (% of the close) for every row, from earlier rows only."""
    units = [units_between(r["prev"], r["day"]) for r in rows]
    per_unit = [r["ret"] / math.sqrt(u) for r, u in zip(rows, units)]
    z_iv = [r["ret"] / r["sigma"] for r in rows]
    iv = [r["sigma"] for r in rows]
    blend, weekday = [], []
    for i, r in enumerate(rows):
        past = per_unit[max(0, i - RV_WINDOW):i]
        if len(past) >= RV_WINDOW:
            rv = _rms(past) * math.sqrt(units[i])
            blend.append(math.sqrt(0.5 * iv[i] ** 2 + 0.5 * rv ** 2))
        else:
            blend.append(None)
        window = list(range(max(0, i - WEEKDAY_WINDOW), i))
        same = [z_iv[j] for j in window if rows[j]["day"].weekday() == r["day"].weekday()]
        weekday.append(iv[i] * _rms(same) / _rms([z_iv[j] for j in window])
                       if len(same) >= WEEKDAY_MIN else None)
    return {"iv": iv, "iv_rv_blend": blend, "iv_weekday": weekday}


def walk_forward(rows: list[dict]) -> dict[str, list[float | None]]:
    """Each method's calibrated width for every row: its raw width times its
    own k from the CAL_WINDOW sessions before, as the forecast does."""
    out = {}
    for m, raw in raw_sigmas(rows).items():
        z = [r["ret"] / s if s else None for r, s in zip(rows, raw)]
        final = []
        for i, s in enumerate(raw):
            past = [x for x in z[max(0, i - CAL_WINDOW):i] if x is not None]
            final.append(s * _clip(_rms(past), K_BOUNDS) if s and len(past) >= K_MIN else None)
        out[m] = final
    return out


def log_score(ret: float, sigma: float) -> float:
    """Log likelihood of the move under a normal band of width `sigma`: higher is better."""
    return -0.5 * math.log(2 * math.pi) - math.log(sigma) - 0.5 * (ret / sigma) ** 2


def compare(rows: list[dict], champion: str = "iv") -> dict:
    """Score every method over the last TRIAL sessions and apply the rule."""
    if champion not in METHODS:
        champion = "iv"
    widths = walk_forward(rows)
    usable = [i for i in range(len(rows)) if all(widths[m][i] for m in METHODS)][-TRIAL:]
    base = {"previous": champion, "champion": champion, "switched": False, "sessions": len(usable),
            "trial": TRIAL, "margin": MARGIN, "labels": LABELS,
            "through": rows[-1]["day"].isoformat() if rows else None}
    if len(usable) < TRIAL:
        return {**base, "scores": {}, "halves": [],
                "reason": f"{len(usable)} sessions scored by every method; {TRIAL} are needed before any can replace another"}

    def mean_scores(idx):
        return {m: round(statistics.mean(log_score(rows[i]["ret"], widths[m][i]) for i in idx), 4) for m in METHODS}

    scores = mean_scores(usable)
    half = len(usable) // 2
    halves = [mean_scores(usable[:half]), mean_scores(usable[half:])]
    challengers = sorted((m for m in METHODS if m != champion), key=lambda m: scores[m], reverse=True)
    best = challengers[0]
    wins = (scores[best] - scores[champion] >= MARGIN and all(h[best] > h[champion] for h in halves))
    if wins:
        reason = (f"{LABELS[best]} scored {scores[best] - scores[champion]:.3f} higher a session over the last "
                  f"{len(usable)}, and higher in both halves: it replaces {LABELS[champion]}")
    else:
        reason = (f"no method beat {LABELS[champion]} by {MARGIN} a session in both halves of the last "
                  f"{len(usable)} sessions; it stays")
    return {**base, "champion": best if wins else champion, "switched": wins, "scores": scores, "halves": halves,
            "reason": reason}


def method_rows(rows: list[dict], method: str) -> list[dict]:
    """The rows with each one's error measured against `method`'s raw width,
    for the forecast's own calibration of that method."""
    raw = raw_sigmas(rows)[method]
    return [{**r, "z": r["ret"] / s} for r, s in zip(rows, raw) if s]


def target_raw_sigma(rows: list[dict], method: str, iv: float, prev, target) -> float:
    """`method`'s raw width for the session being forecast, from `rows` (all before it)."""
    from .day_forecast import sigma_pct
    sig_iv = sigma_pct(iv, prev, target)
    if method == "iv":
        return sig_iv
    if method == "iv_rv_blend":
        past = [r["ret"] / math.sqrt(units_between(r["prev"], r["day"])) for r in rows[-RV_WINDOW:]]
        if len(past) < RV_WINDOW:
            return sig_iv
        rv = _rms(past) * math.sqrt(units_between(prev, target))
        return math.sqrt(0.5 * sig_iv ** 2 + 0.5 * rv ** 2)
    window = rows[-WEEKDAY_WINDOW:]
    z = [r["ret"] / r["sigma"] for r in window]
    same = [x for r, x in zip(window, z) if r["day"].weekday() == target.weekday()]
    return sig_iv * _rms(same) / _rms(z) if len(same) >= WEEKDAY_MIN else sig_iv
