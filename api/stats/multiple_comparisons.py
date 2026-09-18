"""Multiple-comparisons control for the recommendation gate (I5).

Each pattern is judged once on the holdout. With N patterns judged, one of
them clearing t = 2 by luck alone becomes likely as N grows, so the gate
uses a Bonferroni threshold: the one-sided critical value for
FAMILY_ALPHA / N. That keeps the chance of *any* false recommendation
across all patterns near FAMILY_ALPHA.

Replaces an earlier log-scaled heuristic on index expectancy, which needed
no p-value but also had no principled basis; option verdicts now carry a
t-statistic, so the standard correction applies directly.
"""

from statistics import NormalDist

FAMILY_ALPHA = 0.05


def required_t(tests: int, family_alpha: float = FAMILY_ALPHA) -> float:
    return round(NormalDist().inv_cdf(1 - family_alpha / max(tests, 1)), 2)
