import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import (
    compute_dollar_duration,
    compute_dv01,
    compute_extended_risk_metrics,
    compute_fixed_leg_macaulay_duration,
    compute_gamma_dv01,
    compute_leg_dv01,
)

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


def _swap(years, pay_fixed=True, notional=10_000_000, fixed_rate=0.03):
    maturity = dt.date(TRADE_DATE.year + years, TRADE_DATE.month, TRADE_DATE.day)
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, maturity, notional, fixed_rate, pay_fixed=pay_fixed)


# --- Leg DV01 ---

def test_leg_dv01_sums_to_net_dv01_for_payer(curve):
    swap = _swap(10, pay_fixed=True)
    net = compute_dv01(swap, curve)
    legs = compute_leg_dv01(swap, curve)
    assert legs["floating_leg_dv01"] - legs["fixed_leg_dv01"] == pytest.approx(net, rel=1e-9)


def test_leg_dv01_sums_to_net_dv01_for_receiver(curve):
    swap = _swap(10, pay_fixed=False)
    net = compute_dv01(swap, curve)
    legs = compute_leg_dv01(swap, curve)
    assert legs["fixed_leg_dv01"] - legs["floating_leg_dv01"] == pytest.approx(net, rel=1e-9)


def test_leg_dv01_independent_of_pay_receive_direction(curve):
    """The underlying leg PVs (and their bump sensitivities) don't depend on
    which leg is being paid vs received -- only how npv() combines them does."""
    payer = _swap(10, pay_fixed=True)
    receiver = _swap(10, pay_fixed=False)
    assert compute_leg_dv01(payer, curve) == compute_leg_dv01(receiver, curve)


# --- Dollar duration ---

def test_dollar_duration_same_sign_as_dv01(curve):
    swap = _swap(10, pay_fixed=True)
    assert compute_dollar_duration(swap, curve) > 0
    assert compute_dv01(swap, curve) > 0


def test_dollar_duration_less_than_linear_extrapolation_due_to_convexity(curve):
    """Payer swaps have negative dollar convexity (see test_risk_extended.py),
    so the true 100bp move should be SMALLER than naively extrapolating the
    1bp DV01 by 100x."""
    swap = _swap(10, pay_fixed=True)
    dv01 = compute_dv01(swap, curve)
    dollar_duration = compute_dollar_duration(swap, curve)
    assert dollar_duration < dv01 * 100


# --- Gamma DV01 ---

def test_gamma_dv01_payer_receiver_mirror(curve):
    payer = _swap(10, pay_fixed=True)
    receiver = _swap(10, pay_fixed=False)
    assert compute_gamma_dv01(payer, curve) == pytest.approx(-compute_gamma_dv01(receiver, curve), rel=1e-6)


def test_gamma_dv01_nonzero(curve):
    swap = _swap(10, pay_fixed=True)
    assert compute_gamma_dv01(swap, curve) != 0


# --- Fixed-leg Macaulay duration ---

def test_macaulay_duration_less_than_maturity(curve):
    swap = _swap(10)
    duration = compute_fixed_leg_macaulay_duration(swap, curve)
    assert 0 < duration < 10


def test_macaulay_duration_increases_with_maturity(curve):
    short_dur = compute_fixed_leg_macaulay_duration(_swap(5), curve)
    long_dur = compute_fixed_leg_macaulay_duration(_swap(10), curve)
    assert long_dur > short_dur


def test_macaulay_duration_independent_of_notional(curve):
    """Duration is a PV-weighted average TIME, not a dollar amount -- doubling
    notional scales every cashflow's PV equally, leaving the weighted average
    time unchanged."""
    small = compute_fixed_leg_macaulay_duration(_swap(10, notional=1_000_000), curve)
    large = compute_fixed_leg_macaulay_duration(_swap(10, notional=50_000_000), curve)
    assert small == pytest.approx(large, rel=1e-9)


def test_macaulay_duration_zero_notional_is_zero(curve):
    swap = _swap(10, notional=0.0)
    assert compute_fixed_leg_macaulay_duration(swap, curve) == 0.0


# --- Bundled extended metrics ---

def test_extended_risk_metrics_contains_all_fields(curve):
    swap = _swap(10)
    metrics = compute_extended_risk_metrics(swap, curve)
    assert set(metrics.keys()) == {
        "dollar_duration_100bp", "gamma_dv01_50bp",
        "fixed_leg_dv01", "floating_leg_dv01", "fixed_leg_macaulay_duration_years",
    }
    assert all(isinstance(v, float) for v in metrics.values())
