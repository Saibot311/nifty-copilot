from stats.multiple_comparisons import required_bar


def test_bar_never_drops_below_base_even_with_few_hypotheses():
    r = required_bar(num_hypotheses_tested=1, base_expectancy_pct=0.25, base_trades=30)
    assert r.min_expectancy_pct >= 0.25
    assert r.min_trades >= 30


def test_bar_rises_as_hypothesis_count_grows():
    low = required_bar(num_hypotheses_tested=10)
    high = required_bar(num_hypotheses_tested=1000)
    assert high.min_expectancy_pct > low.min_expectancy_pct
    assert high.min_trades > low.min_trades


def test_growth_is_sublinear_not_linear():
    """1000x more hypotheses must not demand anywhere near 1000x the
    effect size -- log-scaling should keep the bar climbable."""
    r10 = required_bar(num_hypotheses_tested=10)
    r10000 = required_bar(num_hypotheses_tested=10_000)
    ratio = r10000.min_expectancy_pct / r10.min_expectancy_pct
    assert ratio < 3  # nowhere close to the 1000x hypothesis-count ratio
