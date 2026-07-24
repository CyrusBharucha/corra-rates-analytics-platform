"""
Bootstraps a continuously-compounded zero curve from:
  - the CORRA overnight fixing (anchors the very short end), and
  - Government of Canada benchmark bond yields (2Y, 3Y, 5Y, 7Y, 10Y, ~30Y),
    treated as semi-annual-pay par bond yields.

This is a manual, from-scratch bootstrap (no QuantLib) so every step can be
explained: for each bond node, we solve the discount factor that makes a par
bond with that coupon and maturity price to 100, given discount factors for
earlier coupon dates already known (or, when a coupon date falls in a gap
between bootstrapped nodes, from flat extrapolation off the last known node).

Gap handling: intermediate coupon dates that fall between the last
bootstrapped node and the node currently being solved for (e.g. pricing the
10Y node uses coupons at 7.5Y, 8.5Y, 9.5Y, which sit beyond the 7Y node) are
priced using linear interpolation between the last known node and the node
being solved - i.e. the unknown zero rate at the new node is used for both
the final cashflow AND the intervening coupons, and we root-find for the
zero rate that makes the bond price to par. This is the standard
self-consistent single-pass bootstrap (equivalent to what a manual
bootstrap does when coupon dates don't line up with quoted maturities).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq

from corra_pricer.curve_builder.curve import YieldCurve
from corra_pricer.curve_builder.interpolation import linear_zero_interpolator

DEFAULT_TENOR_YEARS = {
    "2Y": 2.0,
    "3Y": 3.0,
    "5Y": 5.0,
    "7Y": 7.0,
    "10Y": 10.0,
    "LONG": 30.0,
}

OVERNIGHT_T = 1.0 / 365.0


def _simple_to_continuous(rate_decimal: float, day_fraction: float) -> float:
    """Converts a simple overnight rate (ACT/365) to a continuously-compounded rate."""
    return np.log(1.0 + rate_decimal * day_fraction) / day_fraction


def _generate_coupon_times(maturity: float, freq: int) -> list[float]:
    step = 1.0 / freq
    times = [maturity]
    t = maturity - step
    while t > 1e-6:
        times.append(t)
        t -= step
    return sorted(times)


def bootstrap_zero_curve(
    corra_rate_pct: float,
    benchmark_yields_pct: dict[str, float],
    tenor_years: dict[str, float] | None = None,
    coupon_freq: int = 2,
    interpolation: str = "linear",
    label: str = "GoC-Proxy OIS Zero Curve",
) -> YieldCurve:
    tenor_years = tenor_years or DEFAULT_TENOR_YEARS

    times: list[float] = [OVERNIGHT_T]
    zeros: list[float] = [_simple_to_continuous(corra_rate_pct / 100.0, OVERNIGHT_T)]

    ordered_tenors = sorted(tenor_years.items(), key=lambda kv: kv[1])
    for name, maturity in ordered_tenors:
        v = benchmark_yields_pct.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        par_yield = benchmark_yields_pct[name] / 100.0
        coupon = par_yield / coupon_freq
        coupon_times = _generate_coupon_times(maturity, coupon_freq)

        known_times = np.array(times)
        known_zeros = np.array(zeros)
        last_known_t = known_times[-1]

        def bond_price_error(z_guess: float, known_times=known_times, known_zeros=known_zeros,
                              last_known_t=last_known_t, coupon_times=coupon_times) -> float:
            # Nodes so far, plus a trial node at (maturity, z_guess), interpolated linearly
            # on zero rate. Gap coupons beyond the last known node fall between
            # (last_known_t, known_zeros[-1]) and (maturity, z_guess).
            trial_times = np.append(known_times, maturity)
            trial_zeros = np.append(known_zeros, z_guess)
            interp = linear_zero_interpolator(trial_times, trial_zeros)
            price = 0.0
            for pt in coupon_times[:-1]:
                z = interp(pt)
                price += coupon * 100.0 * np.exp(-z * pt)
            price += (coupon * 100.0 + 100.0) * np.exp(-z_guess * maturity)
            return price - 100.0

        try:
            z_maturity = brentq(bond_price_error, -0.9, 3.0, xtol=1e-10)
        except ValueError as exc:
            raise ValueError(
                f"No discount factor exists for the {name} ({maturity}Y) node that reprices "
                f"its par bond to 100, even scanning zero rates from -90% to +300%. This means "
                f"the PV of coupons implied by already-bootstrapped shorter nodes already exceeds "
                f"par on its own - typically a sign of internally inconsistent/non-arbitrage-free "
                f"input yields (e.g. unrealistically extreme rates), not a solver failure."
            ) from exc

        times.append(maturity)
        zeros.append(z_maturity)

    return YieldCurve(np.array(times), np.array(zeros), interpolation=interpolation, label=label)


def reprice_par_bonds(
    curve: YieldCurve,
    benchmark_yields_pct: dict[str, float],
    tenor_years: dict[str, float] | None = None,
    coupon_freq: int = 2,
) -> dict[str, float]:
    """Reprices each input par bond off an already-built curve and returns
    {tenor: price - 100} residuals - should be ~0 for every tenor if the
    curve is self-consistent. This validates the curve as actually
    delivered to callers (i.e. through curve.discount_factor(), using
    whichever interpolation method the curve was built with), which is a
    meaningfully different check from the bootstrap's own internal
    construction-time gap handling (bond_price_error above always uses
    linear-on-zero-rate for gap coupons regardless of the curve's final
    interpolation method) - so a cubic-spline or log-linear-DF curve can
    show a small nonzero residual here even though the bootstrap itself
    solved each node exactly.
    """
    tenor_years = tenor_years or DEFAULT_TENOR_YEARS
    residuals = {}
    for name, maturity in tenor_years.items():
        v = benchmark_yields_pct.get(name)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        par_yield = benchmark_yields_pct[name] / 100.0
        coupon = par_yield / coupon_freq
        coupon_times = _generate_coupon_times(maturity, coupon_freq)
        price = 0.0
        for pt in coupon_times[:-1]:
            price += coupon * 100.0 * curve.discount_factor(pt)
        price += (coupon * 100.0 + 100.0) * curve.discount_factor(maturity)
        residuals[name] = price - 100.0
    return residuals
