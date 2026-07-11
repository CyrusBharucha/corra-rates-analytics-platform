"""
Property-based tests using Hypothesis: instead of hand-picking example inputs,
Hypothesis generates many randomized inputs per test and checks an invariant
holds for all of them, shrinking to a minimal failing case if it finds one.
These catch classes of bugs (off-by-one scaling, sign errors that only show
up for certain input combinations) that a handful of hand-picked unit tests
can miss.

The curve is built once at module scope (not re-bootstrapped per Hypothesis
example) to keep the test suite fast -- these properties are about the
pricer/risk-engine's behavior given a fixed curve, not about the bootstrap
itself (which has its own dedicated tests).
"""
import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.curve_builder.shocked_curve import parallel_shift
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import compute_dv01

YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
CURVE = bootstrap_zero_curve(2.29, YIELDS_PCT)
TRADE_DATE = dt.date(2026, 7, 9)

notionals = st.floats(min_value=1_000, max_value=500_000_000, allow_nan=False, allow_infinity=False)
fixed_rates = st.floats(min_value=-0.02, max_value=0.15, allow_nan=False, allow_infinity=False)
maturities = st.integers(min_value=1, max_value=30)
bumps = st.floats(min_value=1, max_value=500, allow_nan=False, allow_infinity=False)


def _maturity_date(years: int) -> dt.date:
    return dt.date(TRADE_DATE.year + years, TRADE_DATE.month, TRADE_DATE.day)


def _swap(years, notional, fixed_rate, pay_fixed=True):
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, _maturity_date(years), notional, fixed_rate, pay_fixed=pay_fixed)


@given(notional=notionals, years=maturities, fixed_rate=fixed_rates)
@settings(max_examples=40, deadline=None)
def test_double_notional_doubles_npv(notional, years, fixed_rate):
    swap = _swap(years, notional, fixed_rate)
    doubled = _swap(years, 2 * notional, fixed_rate)
    assert doubled.npv(CURVE) == pytest.approx(2 * swap.npv(CURVE), rel=1e-6, abs=1e-6)


@given(notional=notionals, years=maturities, fixed_rate=fixed_rates)
@settings(max_examples=40, deadline=None)
def test_double_notional_doubles_dv01(notional, years, fixed_rate):
    swap = _swap(years, notional, fixed_rate)
    doubled = _swap(years, 2 * notional, fixed_rate)
    dv01_base = compute_dv01(swap, CURVE)
    dv01_doubled = compute_dv01(doubled, CURVE)
    assert dv01_doubled == pytest.approx(2 * dv01_base, rel=1e-6, abs=1e-6)


@given(notional=notionals, years=maturities,
       rate_a=st.floats(min_value=-0.02, max_value=0.10), rate_b=st.floats(min_value=-0.02, max_value=0.10))
@settings(max_examples=40, deadline=None)
def test_increasing_fixed_coupon_increases_receiver_value(notional, years, rate_a, rate_b):
    if rate_a >= rate_b:
        rate_a, rate_b = rate_b, rate_a
    if rate_a == rate_b:
        return  # degenerate, skip
    receiver_low = _swap(years, notional, rate_a, pay_fixed=False)
    receiver_high = _swap(years, notional, rate_b, pay_fixed=False)
    assert receiver_high.npv(CURVE) >= receiver_low.npv(CURVE)


@given(notional=notionals, years=maturities, fixed_rate=fixed_rates, bump=bumps)
@settings(max_examples=40, deadline=None)
def test_increasing_rates_helps_payer(notional, years, fixed_rate, bump):
    payer = _swap(years, notional, fixed_rate, pay_fixed=True)
    bumped_curve = parallel_shift(CURVE, bump)
    assert payer.npv(bumped_curve) >= payer.npv(CURVE) - 1e-6


@given(notional=notionals, years=maturities, fixed_rate=fixed_rates, bump=bumps)
@settings(max_examples=40, deadline=None)
def test_increasing_rates_hurts_receiver(notional, years, fixed_rate, bump):
    receiver = _swap(years, notional, fixed_rate, pay_fixed=False)
    bumped_curve = parallel_shift(CURVE, bump)
    assert receiver.npv(bumped_curve) <= receiver.npv(CURVE) + 1e-6


@given(notional=notionals,
       years_a=st.integers(min_value=1, max_value=14), years_b=st.integers(min_value=15, max_value=30))
@settings(max_examples=40, deadline=None)
def test_longer_maturity_increases_dv01_magnitude(notional, years_a, years_b):
    short_swap = _swap(years_a, notional, 0.03)
    long_swap = _swap(years_b, notional, 0.03)
    assert abs(compute_dv01(long_swap, CURVE)) > abs(compute_dv01(short_swap, CURVE))


@given(notional=notionals, years=maturities)
@settings(max_examples=40, deadline=None)
def test_payer_receiver_npv_always_exact_negatives(notional, years):
    payer = _swap(years, notional, 0.03, pay_fixed=True)
    receiver = _swap(years, notional, 0.03, pay_fixed=False)
    assert payer.npv(CURVE) == pytest.approx(-receiver.npv(CURVE), rel=1e-9, abs=1e-6)
