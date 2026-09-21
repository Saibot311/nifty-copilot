"""Student's t distribution, without scipy.

The evidence bar used the normal distribution. That is right for large
samples and wrong for the ones this system actually has: a pattern judged on
11 holdout trades has 10 degrees of freedom, and at the Bonferroni level for
19 patterns the true critical value is about 3.5, not the normal 2.79. Using
the normal quantile there lets through results that are not significant.

CDF via the regularized incomplete beta function (continued fraction,
Lentz's method, as in Numerical Recipes 6.4); the inverse by bisection,
which is slow but cannot fail to converge on a monotone function.
"""

import math


def _betacf(a: float, b: float, x: float, max_iter: int = 300, eps: float = 3e-14) -> float:
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    front = math.exp(ln_front)
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def cdf(t: float, df: float) -> float:
    if t == 0:
        return 0.5
    t2 = t * t
    # df/(df+t^2) rounds to exactly 1.0 for small t, flattening the CDF near
    # zero. Use whichever of the two complementary variables is small, since
    # that is the one floating point represents precisely.
    x, y = df / (df + t2), t2 / (df + t2)
    if x < y:
        tail = 0.5 * _betainc(df / 2, 0.5, x)
    else:
        tail = 0.5 * (1 - _betainc(0.5, df / 2, y))
    return 1 - tail if t > 0 else tail


def ppf(p: float, df: float) -> float:
    """Inverse CDF: the t with cdf(t, df) == p."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        if cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-10:
            break
    return (lo + hi) / 2
