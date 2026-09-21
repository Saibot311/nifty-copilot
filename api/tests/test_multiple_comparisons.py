from stats.multiple_comparisons import required_t


def test_single_test_uses_the_ordinary_one_sided_5pct_line():
    assert required_t(1) == 1.64


def test_bar_rises_with_the_number_of_patterns_judged():
    assert required_t(1) < required_t(10) < required_t(26) < required_t(100)


def test_26_patterns_needs_roughly_t_2_9():
    # Bonferroni: one-sided 5% / 26 = 0.19% per test.
    assert 2.8 < required_t(26) < 3.0


def test_small_samples_face_a_higher_bar():
    # Found by the audit: the bar used the normal distribution, 2.79 for 19
    # patterns, while a verdict on 11 holdout trades needs 3.55.
    assert required_t(19) == 2.79
    assert required_t(19, df=10) == 3.55
    assert required_t(19, df=10) > required_t(19, df=29) > required_t(19, df=200) > required_t(19)


def test_no_degrees_of_freedom_means_nothing_can_clear_it():
    assert required_t(19, df=0) == float("inf")
