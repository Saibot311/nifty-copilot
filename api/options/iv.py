"""Implied volatility from the bhavcopy archive — no assumed rates.

For someone buying options, the volatility priced in at entry matters as
much as direction: buy a call when fear is high and the index can rise and
the option still lose, as the premium's volatility drains out of it.

NIFTY options are European, so Black-76 on the forward applies exactly:

    C = D [F N(d1) - K N(d2)]      P = D [K N(-d2) - F N(-d1)]

The forward F and discount factor D are not assumed. Put-call parity,
C - P = D (F - K), is a straight line in K, so fitting C - P against strike
across the liquid near-the-money strikes gives D as minus the slope and F
from the intercept. That absorbs the interest rate (3% to 7% over 2018-26)
and the index's dividend yield without guessing either, and it is exactly
the relationship the audit found these prices obey to a median 0.10% of spot.

Implied vol is found by bisection: slower than Newton's method, but it
cannot diverge on a deep in-the-money option with almost no time value.
"""

import math
from dataclasses import dataclass

SQRT2 = math.sqrt(2.0)
MIN_OI = 1000          # the same liquidity floor the options engine trades on
MIN_PRICE = 0.5        # below this, tick size dominates the price
FIT_WINDOW = 0.05      # strikes within 5% of spot inform the forward
FALLBACK_RATE = 0.065  # only if parity cannot be fitted; recorded when used


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


def black76(F: float, K: float, T: float, sigma: float, D: float, kind: str) -> float:
    """Price of a European call ('CE') or put ('PE') on forward F."""
    if T <= 0 or sigma <= 0:
        return D * max(F - K, 0.0) if kind == "CE" else D * max(K - F, 0.0)
    s = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * s * s) / s
    d2 = d1 - s
    if kind == "CE":
        return D * (F * norm_cdf(d1) - K * norm_cdf(d2))
    return D * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def implied_vol(price: float, F: float, K: float, T: float, D: float, kind: str,
                lo: float = 0.005, hi: float = 3.0) -> float | None:
    """The sigma that reproduces `price`, or None when no sigma can: a price
    at or below intrinsic value, or above the no-arbitrage ceiling, is a
    stale or mis-keyed quote, not a volatility."""
    if T <= 0 or price <= 0 or F <= 0 or K <= 0:
        return None
    intrinsic = D * max(F - K, 0.0) if kind == "CE" else D * max(K - F, 0.0)
    ceiling = D * F if kind == "CE" else D * K
    if price <= intrinsic + 1e-9 or price >= ceiling:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if black76(F, K, T, mid, D, kind) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-7:
            break
    return (lo + hi) / 2


@dataclass
class ForwardFit:
    forward: float
    discount: float
    strikes_used: int
    method: str  # "parity fit" | "fallback"


def fit_forward(calls: dict[float, float], puts: dict[float, float], spot: float, T: float) -> ForwardFit:
    """Least-squares line through C - P against K over near-the-money
    strikes quoted on both sides. Falls back to an assumed rate only when
    the fit is impossible or implausible, and says so."""
    ks = sorted(k for k in set(calls) & set(puts) if abs(k / spot - 1) <= FIT_WINDOW)
    if len(ks) >= 3:
        y = [calls[k] - puts[k] for k in ks]
        n, mk, my = len(ks), sum(ks) / len(ks), sum(y) / len(ks)
        sxx = sum((k - mk) ** 2 for k in ks)
        if sxx > 0:
            slope = sum((k - mk) * (v - my) for k, v in zip(ks, y)) / sxx
            intercept = my - slope * mk
            D = -slope
            if 0.9 < D <= 1.001:
                F = intercept / D
                if abs(F / spot - 1) < 0.03:
                    return ForwardFit(F, min(D, 1.0), n, "parity fit")
    D = math.exp(-FALLBACK_RATE * T)
    return ForwardFit(spot / D, D, 0, "fallback")


def atm_iv(calls: dict[float, float], puts: dict[float, float], fit: ForwardFit, T: float) -> float | None:
    """Volatility at the forward: interpolated between the two strikes that
    bracket it, each strike's vol taken as the mean of its call and put vols
    (the same number, if parity holds — averaging halves close-price noise)."""
    def vol_at(k: float) -> float | None:
        vs = [v for v in (
            implied_vol(calls[k], fit.forward, k, T, fit.discount, "CE") if k in calls else None,
            implied_vol(puts[k], fit.forward, k, T, fit.discount, "PE") if k in puts else None,
        ) if v is not None]
        return sum(vs) / len(vs) if vs else None

    strikes = sorted(set(calls) | set(puts))
    below = [k for k in strikes if k <= fit.forward]
    above = [k for k in strikes if k > fit.forward]
    k_lo = below[-1] if below else None
    k_hi = above[0] if above else None
    v_lo = vol_at(k_lo) if k_lo is not None else None
    v_hi = vol_at(k_hi) if k_hi is not None else None
    if v_lo is not None and v_hi is not None:
        w = (fit.forward - k_lo) / (k_hi - k_lo)
        return v_lo + w * (v_hi - v_lo)
    return v_lo if v_lo is not None else v_hi


def constant_maturity(points: list[tuple[float, float]], target_days: float = 30) -> float | None:
    """30-day vol from the expiries around it, interpolating total variance
    (sigma^2 T) linearly in time — the way VIX-style indices are built, and
    the only interpolation that cannot produce an arbitrage."""
    pts = sorted((T, v) for T, v in points if v is not None and T > 0)
    if not pts:
        return None
    t = target_days / 365
    if t <= pts[0][0]:
        return pts[0][1]
    if t >= pts[-1][0]:
        return pts[-1][1]
    for (t1, v1), (t2, v2) in zip(pts, pts[1:]):
        if t1 <= t <= t2:
            w1, w2 = v1 * v1 * t1, v2 * v2 * t2
            w = w1 + (w2 - w1) * (t - t1) / (t2 - t1)
            return math.sqrt(max(w, 0.0) / t)
    return None
