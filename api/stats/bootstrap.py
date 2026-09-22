"""Bootstrap confidence intervals.

A holdout result is one number from a handful of trades, and option returns
are wildly skewed — one trade of +236% and eleven small losses is a normal
sample here. A t-statistic says whether the mean is distinguishable from a
baseline; it does not say how uncertain that mean is. Resampling the trades
with replacement does: it answers "if these trades had come out in a
different order, or a different sample of the same kind, what range of
averages would we have seen?"

Fixed seed, so a verdict never changes because a research run was repeated.
Percentile intervals — no distributional assumption, which is the point.
"""

import random
import statistics

SEED = 20260922
DEFAULT_RESAMPLES = 5000


def _mean_of_resample(values: list[float], rng: random.Random) -> float:
    n = len(values)
    return statistics.mean(rng.choices(values, k=n))


def mean_ci(values: list[float], confidence: float = 0.95, resamples: int = DEFAULT_RESAMPLES) -> dict | None:
    """Percentile interval for the mean of `values`."""
    if len(values) < 3:
        return None
    rng = random.Random(SEED)
    means = sorted(_mean_of_resample(values, rng) for _ in range(resamples))
    lo = means[int((1 - confidence) / 2 * resamples)]
    hi = means[min(resamples - 1, int((1 + confidence) / 2 * resamples))]
    return {"mean": round(statistics.mean(values), 2), "low": round(lo, 2), "high": round(hi, 2),
            "confidence": confidence, "resamples": resamples, "n": len(values)}


def difference_ci(values: list[float], baseline: list[float], confidence: float = 0.95,
                  resamples: int = DEFAULT_RESAMPLES) -> dict | None:
    """Percentile interval for the edge — the signal's mean minus the
    no-signal mean — resampling both sides independently. An interval that
    contains zero means the edge could be nothing, whatever the point
    estimate looks like."""
    if len(values) < 3 or len(baseline) < 3:
        return None
    rng = random.Random(SEED)
    diffs = sorted(_mean_of_resample(values, rng) - _mean_of_resample(baseline, rng) for _ in range(resamples))
    lo = diffs[int((1 - confidence) / 2 * resamples)]
    hi = diffs[min(resamples - 1, int((1 + confidence) / 2 * resamples))]
    return {"edge": round(statistics.mean(values) - statistics.mean(baseline), 2),
            "low": round(lo, 2), "high": round(hi, 2), "includes_zero": lo <= 0 <= hi,
            "confidence": confidence, "resamples": resamples}
