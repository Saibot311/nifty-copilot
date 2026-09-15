"""A simple, documented multiple-comparisons correction — explicitly
promised in the project's own spec ("as the count grows, the bar for
calling something validated rises accordingly") and, until now, never
actually built. The recommendation gate used fixed thresholds regardless
of how many strategies/parameters/strike-expiry combinations had already
been tested against the same underlying data.

This is NOT a rigorous Benjamini-Hochberg false-discovery-rate procedure
-- that needs a p-value per hypothesis, which nothing here computes. It's
a transparent, conservative heuristic in the same spirit: as the number of
things tried against the same data grows, require a proportionally larger
effect size and sample before calling anything worth acting on. The
formula is simple on purpose, so it's auditable rather than a black box.

Scaling: scale = 1 + log10(max(n, 10)) / 2. At n=10 (the floor), scale=1.5;
at n=100, scale=2.0; at n=1000, scale=2.5; at n=10000, scale=3.0. Growth
is deliberately slow (log-scaled) -- linear scaling with hypothesis count
would make the bar nearly impossible to clear once past a few hundred
tests, which stops being a useful signal and just shuts the system down.
"""

import math
from dataclasses import dataclass


@dataclass
class RequiredBar:
    num_hypotheses_tested: int
    scale_factor: float
    min_expectancy_pct: float
    min_trades: int
    methodology_note: str


def required_bar(
    num_hypotheses_tested: int,
    base_expectancy_pct: float = 0.25,
    base_trades: int = 30,
) -> RequiredBar:
    n = max(num_hypotheses_tested, 1)
    scale = 1.0 + math.log10(max(n, 10)) / 2

    return RequiredBar(
        num_hypotheses_tested=n,
        scale_factor=round(scale, 3),
        min_expectancy_pct=round(base_expectancy_pct * scale, 3),
        min_trades=max(base_trades, round(base_trades * scale)),
        methodology_note=(
            f"{n} hypotheses logged so far -> scale factor {scale:.2f}x. This is a simple, "
            "log-scaled heuristic, not a rigorous FDR/Benjamini-Hochberg correction (that needs a "
            "p-value per hypothesis, which isn't computed here) -- but it moves in the right "
            "direction: the more things tested against the same data, the larger the effect size "
            "and sample required before anything is treated as real rather than noise."
        ),
    )
