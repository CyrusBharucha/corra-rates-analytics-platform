"""
Regression tests: pin known-good outputs from a fixed, hardcoded market
snapshot (NOT a live API pull -- these must be 100% reproducible). If a
future change to the bootstrap, pricer, or risk engine causes any of these
to drift outside tolerance, it's either an intentional methodology change
(update the pinned values with a clear commit message explaining why) or a
real regression (fix the code). Either way, this test forces that
conversation instead of letting the deviation pass silently.

Baseline captured from: 2026-07-09 BoC Valet market snapshot
  CORRA fixing: 2.29%
  GoC benchmark yields: 2Y=2.80% 3Y=2.91% 5Y=3.12% 7Y=3.26% 10Y=3.52% LONG=3.93%
"""
import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import build_risk_report

PINNED_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
PINNED_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)
MATURITY_5Y = dt.date(2031, 7, 9)

# Pinned baseline values (see docstring for provenance).
EXPECTED_ZERO_RATES_PCT = {
    2.0: 2.784892,
    3.0: 2.895373,
    5.0: 3.110903,
    7.0: 3.257354,
    10.0: 3.543971,
    30.0: 4.065240,
}
EXPECTED_FAIR_RATE_PCT = 3.145224
EXPECTED_FIXED_LEG_PV = 1_374_780.77
EXPECTED_FLOATING_LEG_PV = 1_441_330.93
EXPECTED_NPV_AT_3PCT = 66_550.16
EXPECTED_DV01 = 4_684.27
EXPECTED_PV01 = 4_582.60
EXPECTED_KRD = {"2Y": 176.53, "5Y": 4_505.34, "10Y": 2.42, "30Y": 0.00}
EXPECTED_CONVEXITY = -2.288


@pytest.fixture
def curve():
    return bootstrap_zero_curve(PINNED_CORRA_PCT, PINNED_YIELDS_PCT)


@pytest.fixture
def swap_at_3pct():
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True)


def test_regression_zero_rates(curve):
    for t, expected_pct in EXPECTED_ZERO_RATES_PCT.items():
        assert curve.zero_rate(t) * 100 == pytest.approx(expected_pct, abs=1e-4)


def test_regression_fair_rate(curve, swap_at_3pct):
    assert swap_at_3pct.fair_rate(curve) * 100 == pytest.approx(EXPECTED_FAIR_RATE_PCT, abs=1e-4)


def test_regression_leg_pvs(curve, swap_at_3pct):
    assert swap_at_3pct.fixed_leg_pv(curve) == pytest.approx(EXPECTED_FIXED_LEG_PV, abs=1.0)
    assert swap_at_3pct.floating_leg_pv(curve) == pytest.approx(EXPECTED_FLOATING_LEG_PV, abs=1.0)


def test_regression_npv(curve, swap_at_3pct):
    assert swap_at_3pct.npv(curve) == pytest.approx(EXPECTED_NPV_AT_3PCT, abs=1.0)


def test_regression_dv01(curve, swap_at_3pct):
    report = build_risk_report(swap_at_3pct, curve)
    assert report.dv01 == pytest.approx(EXPECTED_DV01, abs=0.5)


def test_regression_pv01(curve, swap_at_3pct):
    report = build_risk_report(swap_at_3pct, curve)
    assert report.pv01 == pytest.approx(EXPECTED_PV01, abs=0.5)


def test_regression_krd(curve, swap_at_3pct):
    report = build_risk_report(swap_at_3pct, curve)
    for bucket, expected in EXPECTED_KRD.items():
        assert report.krd[bucket] == pytest.approx(expected, abs=0.5)


def test_regression_convexity(curve, swap_at_3pct):
    report = build_risk_report(swap_at_3pct, curve)
    assert report.convexity == pytest.approx(EXPECTED_CONVEXITY, abs=0.01)


def test_regression_full_snapshot_reproducible_end_to_end(curve, swap_at_3pct):
    """One combined check that reruns the whole pipeline and confirms nothing
    upstream (bootstrap, pricer, risk engine) silently drifted."""
    report = build_risk_report(swap_at_3pct, curve)
    assert swap_at_3pct.fair_rate(curve) * 100 == pytest.approx(EXPECTED_FAIR_RATE_PCT, abs=1e-4)
    assert report.dv01 == pytest.approx(EXPECTED_DV01, abs=0.5)
    assert sum(report.krd.values()) == pytest.approx(report.dv01, abs=1.0)
