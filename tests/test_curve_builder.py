import numpy as np
import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.curve_builder.curve import YieldCurve

SAMPLE_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
SAMPLE_CORRA_PCT = 2.29


def test_discount_factor_at_zero_is_one():
    curve = bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT)
    assert curve.discount_factor(0) == pytest.approx(1.0)


def test_discount_factors_are_monotonically_decreasing():
    curve = bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT)
    query_times = np.linspace(0.01, 30, 60)
    dfs = [curve.discount_factor(t) for t in query_times]
    assert all(dfs[i] > dfs[i + 1] for i in range(len(dfs) - 1))


def test_bootstrapped_par_bonds_price_to_par():
    """Reprices each benchmark bond off the bootstrapped curve and checks it comes back to par --
    this is the core correctness check for the bootstrap."""
    curve = bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT)
    tenor_years = {"2Y": 2.0, "3Y": 3.0, "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "LONG": 30.0}
    for name, maturity in tenor_years.items():
        par_yield = SAMPLE_YIELDS_PCT[name] / 100.0
        coupon = par_yield / 2
        coupon_times = [maturity - 0.5 * k for k in range(int(maturity * 2))][::-1]
        price = sum(coupon * 100 * curve.discount_factor(t) for t in coupon_times)
        price += 100 * curve.discount_factor(maturity)
        assert price == pytest.approx(100.0, abs=0.05), f"{name} bond mispriced: {price}"


def test_all_interpolation_methods_agree_at_nodes():
    for method in ["linear", "log_linear_df", "cubic_spline"]:
        curve = bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT, interpolation=method)
        for t, z in zip(curve.times, curve.zero_rates):
            assert curve.zero_rate(t) == pytest.approx(z, abs=1e-8)


def test_parallel_shift_moves_every_node():
    curve = bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT)
    shifted = curve.with_parallel_shift(25)
    for t in curve.times:
        assert shifted.zero_rate(t) == pytest.approx(curve.zero_rate(t) + 0.0025, abs=1e-8)
