"""Student's t, implemented without scipy, checked against printed tables.
If any of these drift, every significance bar in the system is wrong."""

import pytest

from stats.student_t import cdf, ppf


@pytest.mark.parametrize("p,df,table", [
    (0.975, 1, 12.706), (0.975, 10, 2.228), (0.995, 10, 3.169), (0.975, 30, 2.042),
    (0.95, 5, 2.015), (0.999, 20, 3.552), (0.975, 1000, 1.962),
])
def test_matches_printed_tables(p, df, table):
    assert ppf(p, df) == pytest.approx(table, abs=0.002)


def test_cdf_and_ppf_are_inverses():
    for df in (2, 9, 40):
        for p in (0.1, 0.5, 0.9, 0.995):
            assert cdf(ppf(p, df), df) == pytest.approx(p, abs=1e-8)


def test_symmetric_about_zero():
    assert cdf(0.0, 7) == pytest.approx(0.5)
    assert ppf(0.025, 12) == pytest.approx(-ppf(0.975, 12))


def test_approaches_the_normal_for_large_samples():
    from statistics import NormalDist
    assert ppf(0.99, 100_000) == pytest.approx(NormalDist().inv_cdf(0.99), abs=1e-3)
