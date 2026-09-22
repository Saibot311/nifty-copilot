"""Bootstrap intervals. They must be reproducible, must widen as the sample
shrinks, must not pretend to know anything from two trades, and must report
an edge that could be zero as one that includes zero."""

import random

import pytest

from stats.bootstrap import difference_ci, mean_ci


def test_the_same_trades_always_give_the_same_interval():
    xs = [5.0, -100.0, 240.0, -30.0, 12.0, -55.0, 3.0]
    assert mean_ci(xs) == mean_ci(xs)


def test_too_few_trades_get_no_interval():
    assert mean_ci([1.0, 2.0]) is None
    assert difference_ci([1.0, 2.0, 3.0], [1.0, 2.0]) is None


def test_the_interval_brackets_the_mean_and_widens_with_fewer_trades():
    rng = random.Random(7)
    big = [rng.gauss(10, 50) for _ in range(400)]
    small = big[:12]
    wide, narrow = mean_ci(small), mean_ci(big)
    assert narrow["low"] <= narrow["mean"] <= narrow["high"]
    assert (wide["high"] - wide["low"]) > (narrow["high"] - narrow["low"])


def test_an_edge_that_could_be_nothing_says_so():
    rng = random.Random(3)
    same = [rng.gauss(0, 40) for _ in range(60)]
    other = [rng.gauss(0, 40) for _ in range(60)]
    assert difference_ci(same, other)["includes_zero"] is True
    clear = [x + 500 for x in same]
    assert difference_ci(clear, other)["includes_zero"] is False


def test_a_lone_huge_winner_shows_up_as_a_wide_interval():
    # The shape of a real option-buying sample: eleven losses and one +236%.
    xs = [-100.0] * 11 + [236.0]
    ci = mean_ci(xs)
    assert ci["low"] < ci["mean"] < ci["high"]
    assert ci["high"] - ci["low"] > 50
    assert mean_ci(xs) == pytest.approx(ci)
