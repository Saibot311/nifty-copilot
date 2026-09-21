"""Multiple-comparisons control for the recommendation gate (I5).

Each pattern is judged once on the holdout. With N patterns judged, one of
them clearing t = 2 by luck alone becomes likely as N grows, so the gate
uses a Bonferroni threshold: the one-sided critical value for
FAMILY_ALPHA / N. That keeps the chance of *any* false recommendation
across all patterns near FAMILY_ALPHA.

The critical value comes from Student's t at the result's own degrees of
freedom. It used to come from the normal distribution, which is only right
for large samples: at the Bonferroni level for 19 patterns the normal bar is
2.79, but a verdict resting on 11 holdout trades needs 3.55. Using the
normal value there lets through results that are not significant.
"""

from statistics import NormalDist

from . import student_t

FAMILY_ALPHA = 0.05


def required_t(tests: int, df: int | None = None, family_alpha: float = FAMILY_ALPHA) -> float:
    """The t a result must clear. `df` is the result's degrees of freedom
    (holdout trades minus one); without it, the large-sample limit — which
    is the lowest the bar can ever be, so the right figure to quote as
    'at least'."""
    p = 1 - family_alpha / max(tests, 1)
    if df is None:
        return round(NormalDist().inv_cdf(p), 2)
    if df < 1:
        return float("inf")
    return round(student_t.ppf(p, df), 2)
