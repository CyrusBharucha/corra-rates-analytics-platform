import datetime as dt
import math

import numpy as np
import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.curve_builder.shocked_curve import parallel_shift
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import build_risk_report, compute_dv01

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)


def _assert_finite(x):
    assert math.isfinite(x), f"got non-finite value: {x}"


# --- No NaNs / no infinities across a battery of curve queries ---

def test_no_nans_or_infinities_across_curve_queries():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    for t in np.linspace(0, 100, 200):
        _assert_finite(curve.zero_rate(t))
        _assert_finite(curve.discount_factor(t))
        assert not math.isnan(curve.zero_rate(t))


# --- No divide-by-zero: PV01/annuity for a very short (1-day) swap ---

def test_no_divide_by_zero_on_very_short_swap():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, TRADE_DATE + dt.timedelta(days=1),
                         10_000_000, 0.03, pay_fixed=True)
    _assert_finite(swap.annuity(curve))
    assert swap.annuity(curve) > 0
    _assert_finite(swap.fair_rate(curve))
    _assert_finite(swap.npv(curve))


# --- Root-finding convergence at extreme yield inputs ---

@pytest.mark.parametrize("corra_pct,yields_pct", [
    (0.0001, {"2Y": 0.001, "3Y": 0.002, "5Y": 0.003, "7Y": 0.004, "10Y": 0.005, "LONG": 0.006}),  # tiny rates
    (18.0, {"2Y": 17.0, "3Y": 18.0, "5Y": 20.0, "7Y": 21.0, "10Y": 22.0, "LONG": 24.0}),  # very high but feasible
    (-5.0, {"2Y": -4.0, "3Y": -3.0, "5Y": -2.0, "7Y": -1.0, "10Y": 0.5, "LONG": 2.0}),  # deeply negative
])
def test_bootstrap_root_finding_converges_at_extremes(corra_pct, yields_pct):
    curve = bootstrap_zero_curve(corra_pct, yields_pct)
    for t in [2, 3, 5, 7, 10, 30]:
        _assert_finite(curve.zero_rate(t))
        assert curve.discount_factor(t) > 0


def test_bootstrap_fails_gracefully_on_genuinely_infeasible_yields():
    """At sufficiently extreme, front-loaded coupon levels (e.g. 80%+ semi-annual
    coupons), the PV of coupons implied by already-bootstrapped shorter nodes can
    exceed par on its own -- no discount factor at any level reprices the bond to
    100. This isn't a solver bug, it's genuine infeasibility, and the bootstrap
    should raise a clear, diagnostic error rather than a cryptic scipy stack trace
    or (worse) silently returning a wrong answer."""
    infeasible = {"2Y": 80.0, "3Y": 82.0, "5Y": 85.0, "7Y": 87.0, "10Y": 90.0, "LONG": 95.0}
    with pytest.raises(ValueError, match="No discount factor exists"):
        bootstrap_zero_curve(78.0, infeasible)


# --- Tiny rates ---

def test_tiny_rates_stable():
    tiny = {"2Y": 0.0001, "3Y": 0.0002, "5Y": 0.0003, "7Y": 0.0004, "10Y": 0.0005, "LONG": 0.0006}
    curve = bootstrap_zero_curve(0.00005, tiny)
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 7, 9), 10_000_000, 0.00001, pay_fixed=True)
    _assert_finite(swap.npv(curve))
    _assert_finite(compute_dv01(swap, curve))


# --- Huge rates ---

def test_huge_rates_stable():
    huge = {"2Y": 17.0, "3Y": 18.0, "5Y": 20.0, "7Y": 21.0, "10Y": 22.0, "LONG": 24.0}
    curve = bootstrap_zero_curve(18.0, huge)
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 7, 9), 10_000_000, 0.20, pay_fixed=True)
    _assert_finite(swap.npv(curve))
    _assert_finite(compute_dv01(swap, curve))


# --- Tiny maturities ---

def test_tiny_maturity_stable():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, TRADE_DATE + dt.timedelta(days=1),
                         10_000_000, 0.03, pay_fixed=True)
    _assert_finite(swap.npv(curve))
    report = build_risk_report(swap, curve)
    _assert_finite(report.dv01)
    _assert_finite(report.convexity)


# --- Huge maturities (well beyond the last curve node -- pure extrapolation) ---

def test_huge_maturity_stable():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(TRADE_DATE.year + 100, TRADE_DATE.month, TRADE_DATE.day),
                         10_000_000, 0.04, pay_fixed=True)
    _assert_finite(swap.npv(curve))
    _assert_finite(compute_dv01(swap, curve))


# --- No NaN/inf propagation through a large parallel shock ---

def test_large_shock_no_nan_or_inf():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    shocked = parallel_shift(curve, 2000)  # +2000bp = +20%
    for t in [1, 5, 10, 30]:
        _assert_finite(shocked.zero_rate(t))
        _assert_finite(shocked.discount_factor(t))
