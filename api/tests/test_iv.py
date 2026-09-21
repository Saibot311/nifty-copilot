"""Implied volatility. Every IV figure the dashboard shows rests on these."""

import math

import pytest

from options.iv import (ForwardFit, atm_iv, black76, constant_maturity, fit_forward, implied_vol)


def test_matches_hulls_worked_example():
    # Hull, Options Futures and Other Derivatives: a European put on a
    # future at 20, strike 20, r 9%, 4 months, vol 25% is worth 1.12.
    D = math.exp(-0.09 * 4 / 12)
    assert black76(20, 20, 4 / 12, 0.25, D, "PE") == pytest.approx(1.12, abs=0.005)


def test_put_call_parity_holds():
    F, K, T, D = 25000, 24500, 30 / 365, 0.995
    c, p = black76(F, K, T, 0.14, D, "CE"), black76(F, K, T, 0.14, D, "PE")
    assert c - p == pytest.approx(D * (F - K), abs=1e-6)


@pytest.mark.parametrize("kind,K,sigma", [("CE", 25500, 0.12), ("PE", 24000, 0.22), ("CE", 22000, 0.35)])
def test_price_to_vol_round_trip(kind, K, sigma):
    F, T, D = 25000, 21 / 365, 0.996
    assert implied_vol(black76(F, K, T, sigma, D, kind), F, K, T, D, kind) == pytest.approx(sigma, abs=1e-5)


def test_a_price_at_or_below_intrinsic_has_no_vol():
    # A stale or mis-keyed quote, not a volatility.
    assert implied_vol(400.0, 25000, 24500, 0.05, 1.0, "CE") is None


def _chain(F, D, T, sigma, strikes):
    return ({k: black76(F, k, T, sigma, D, "CE") for k in strikes},
            {k: black76(F, k, T, sigma, D, "PE") for k in strikes})


def test_the_forward_and_discount_come_back_out_of_parity():
    # No interest rate or dividend assumed: both are read off the prices.
    F, D, T = 25137.0, 0.9921, 45 / 365
    calls, puts = _chain(F, D, T, 0.15, range(24000, 26100, 100))
    fit = fit_forward(calls, puts, spot=25000, T=T)
    assert fit.method == "parity fit"  # 6.4% implied rate: plausible, so kept
    assert fit.forward == pytest.approx(F, abs=0.5) and fit.discount == pytest.approx(D, abs=1e-5)


def test_atm_vol_is_recovered_from_a_chain():
    F, D, T = 25137.0, 0.9921, 45 / 365
    calls, puts = _chain(F, D, T, 0.15, range(24000, 26100, 100))
    assert atm_iv(calls, puts, ForwardFit(F, D, 21, "parity fit"), T) == pytest.approx(0.15, abs=1e-4)


def test_one_two_sided_strike_is_enough_for_a_forward():
    # One call and put at the same strike pin the forward by parity; the
    # discount factor then has to be assumed, and the method says so.
    fit = fit_forward({25000: 200.0}, {25000: 210.0}, spot=25000, T=30 / 365)
    assert fit.method == "parity forward" and fit.strikes_used == 1
    assert fit.forward == pytest.approx(25000 - 10 / fit.discount)


def test_no_two_sided_strike_falls_back_and_says_so():
    fit = fit_forward({25000: 200.0}, {24000: 210.0}, spot=25000, T=30 / 365)
    assert fit.method == "fallback" and fit.strikes_used == 0


def test_thirty_day_vol_interpolates_total_variance():
    # 20% at 15 days and 20% at 45 days is 20% at 30 days; a flat term
    # structure must stay flat.
    assert constant_maturity([(15 / 365, 0.2), (45 / 365, 0.2)]) == pytest.approx(0.2)
    v = constant_maturity([(15 / 365, 0.10), (45 / 365, 0.20)])
    # total variance: 0.01*15 = 0.15 and 0.04*45 = 1.8 -> 0.975 at 30 days
    assert v == pytest.approx(math.sqrt(0.975 / 30), rel=1e-9)


def test_an_implausible_discount_factor_is_not_believed():
    # Found on 2024-06-04: mistimed closes gave a 9-day D of 0.978, an 88%
    # interest rate. Parity still gives the forward; D falls back to a rate.
    F, T = 21877.0, 9 / 365
    calls, puts = {}, {}
    for i, k in enumerate(range(21000, 22900, 50)):
        c = black76(F, k, T, 0.3, 0.9983, "CE") + 0.024 * (k - 21000) * (i % 2)
        calls[k], puts[k] = c, black76(F, k, T, 0.3, 0.9983, "PE")
    fit = fit_forward(calls, puts, spot=21884.5, T=T)
    r = -math.log(fit.discount) / T
    assert -0.02 <= r <= 0.15
    assert fit.forward == pytest.approx(F, abs=40)


def test_no_atm_vol_without_a_strike_near_the_forward():
    # March 2020: the index fell faster than NSE listed strikes. A vol read
    # 5% away is skew, not at-the-money.
    F, D, T = 7622.0, 0.998, 9 / 365
    calls = {k: black76(F, k, T, 0.9, D, "CE") for k in range(8100, 8600, 100)}
    puts = {k: black76(F, k, T, 0.9, D, "PE") for k in range(8100, 8600, 100)}
    assert atm_iv(calls, puts, ForwardFit(F, D, 5, "parity forward"), T) is None
