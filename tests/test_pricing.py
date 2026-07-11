import datetime as dt
import math

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


def _maturity(years: int) -> dt.date:
    return dt.date(TRADE_DATE.year + years, TRADE_DATE.month, TRADE_DATE.day)


def _swap(curve_maturity_years, notional=10_000_000, fixed_rate=0.03, pay_fixed=True):
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, _maturity(curve_maturity_years),
                         notional, fixed_rate, pay_fixed=pay_fixed)


# --- Basics ---

def test_fair_swap_npv_is_zero(curve):
    swap = _swap(5)
    swap.fixed_rate = swap.fair_rate(curve)
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)


def test_payer_receiver_exact_mirrors(curve):
    payer = _swap(5, pay_fixed=True)
    receiver = _swap(5, pay_fixed=False)
    assert payer.npv(curve) == pytest.approx(-receiver.npv(curve), abs=1e-6)


def test_zero_notional_gives_zero_npv(curve):
    swap = _swap(5, notional=0.0)
    assert swap.npv(curve) == pytest.approx(0.0)


def test_zero_coupon_behaves_correctly(curve):
    """fixed_rate=0 -> fixed leg contributes nothing; NPV is purely the (signed) floating leg."""
    payer = _swap(5, fixed_rate=0.0, pay_fixed=True)
    assert payer.fixed_leg_pv(curve) == pytest.approx(0.0)
    assert payer.npv(curve) == pytest.approx(payer.floating_leg_pv(curve))

    receiver = _swap(5, fixed_rate=0.0, pay_fixed=False)
    assert receiver.npv(curve) == pytest.approx(-receiver.floating_leg_pv(curve))


# --- Maturity sweep ---

@pytest.mark.parametrize("years", [1, 2, 3, 5, 7, 10, 30])
def test_maturity_sweep_fair_rate_reprices_to_zero(curve, years):
    swap = _swap(years)
    fair = swap.fair_rate(curve)
    assert math.isfinite(fair)
    swap.fixed_rate = fair
    assert swap.npv(curve) == pytest.approx(0.0, abs=5.0)


@pytest.mark.parametrize("years", [1, 2, 3, 5, 7, 10, 30])
def test_maturity_sweep_npv_finite_at_fixed_rate(curve, years):
    swap = _swap(years, fixed_rate=0.03)
    npv = swap.npv(curve)
    assert math.isfinite(npv)


# --- Rate sweep ---

@pytest.mark.parametrize("rate_pct", [0.0, 1.0, 2.0, 5.0, 10.0])
def test_rate_sweep_npv_finite(curve, rate_pct):
    swap = _swap(5, fixed_rate=rate_pct / 100.0)
    assert math.isfinite(swap.npv(curve))


def test_rate_sweep_payer_npv_monotonically_decreasing_in_fixed_rate(curve):
    rates = [0.0, 0.01, 0.02, 0.05, 0.10]
    npvs = []
    for r in rates:
        swap = _swap(5, fixed_rate=r)
        npvs.append(swap.npv(curve))
    assert all(npvs[i] > npvs[i + 1] for i in range(len(npvs) - 1))


# --- Stress ---

def test_pricing_under_negative_rate_curve():
    negative = {"2Y": -0.20, "3Y": -0.10, "5Y": 0.05, "7Y": 0.15, "10Y": 0.30, "LONG": 0.60}
    curve = bootstrap_zero_curve(-0.30, negative)
    swap = _swap(5)
    swap.fixed_rate = swap.fair_rate(curve)
    assert math.isfinite(swap.npv(curve))
    assert swap.npv(curve) == pytest.approx(0.0, abs=5.0)


def test_pricing_under_massive_rate_curve():
    massive = {"2Y": 15.0, "3Y": 16.0, "5Y": 18.0, "7Y": 19.0, "10Y": 20.0, "LONG": 22.0}
    curve = bootstrap_zero_curve(14.0, massive)
    swap = _swap(5)
    swap.fixed_rate = swap.fair_rate(curve)
    assert math.isfinite(swap.npv(curve))
    assert swap.npv(curve) == pytest.approx(0.0, abs=50.0)


def test_pricing_under_flat_curve():
    flat = {k: 3.00 for k in NORMAL_YIELDS_PCT}
    curve = bootstrap_zero_curve(3.00, flat)
    swap = _swap(5)
    fair = swap.fair_rate(curve)
    assert fair == pytest.approx(0.03, abs=1e-3)


def test_pricing_under_inverted_curve():
    inverted = {"2Y": 5.00, "3Y": 4.70, "5Y": 4.30, "7Y": 4.00, "10Y": 3.70, "LONG": 3.50}
    curve = bootstrap_zero_curve(5.20, inverted)
    swap = _swap(5)
    swap.fixed_rate = swap.fair_rate(curve)
    assert math.isfinite(swap.npv(curve))
    assert swap.npv(curve) == pytest.approx(0.0, abs=5.0)


def test_receiver_gains_on_massive_rate_curve_vs_normal(curve):
    massive = {"2Y": 15.0, "3Y": 16.0, "5Y": 18.0, "7Y": 19.0, "10Y": 20.0, "LONG": 22.0}
    high_curve = bootstrap_zero_curve(14.0, massive)
    receiver = _swap(5, fixed_rate=0.03, pay_fixed=False)
    assert receiver.npv(high_curve) < receiver.npv(curve)
