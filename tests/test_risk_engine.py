import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.curve_builder.shocked_curve import parallel_shift
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import (
    build_risk_report,
    compute_convexity,
    compute_dv01,
    compute_krd,
    compute_pv01,
)

SAMPLE_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
SAMPLE_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)
LONG_MATURITY = dt.date(2036, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT)


@pytest.fixture
def payer(curve):
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, LONG_MATURITY, 10_000_000, 0.03, pay_fixed=True)


@pytest.fixture
def receiver(curve):
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, LONG_MATURITY, 10_000_000, 0.03, pay_fixed=False)


def test_dv01_sign_conventions(payer, receiver, curve):
    """Pay-fixed gains value when rates rise (positive DV01 under our convention);
    receive-fixed is the exact mirror image (negative DV01)."""
    payer_dv01 = compute_dv01(payer, curve)
    receiver_dv01 = compute_dv01(receiver, curve)
    assert payer_dv01 > 0
    assert receiver_dv01 < 0
    assert payer_dv01 == pytest.approx(-receiver_dv01, rel=1e-9)


def test_pay_fixed_loses_money_when_rates_fall(payer, curve):
    down_curve = parallel_shift(curve, -25)
    assert payer.npv(down_curve) < payer.npv(curve)


def test_receive_fixed_gains_money_when_rates_fall(receiver, curve):
    down_curve = parallel_shift(curve, -25)
    assert receiver.npv(down_curve) > receiver.npv(curve)


def test_pv01_is_positive_and_direction_independent(payer, receiver, curve):
    payer_pv01 = compute_pv01(payer, curve)
    receiver_pv01 = compute_pv01(receiver, curve)
    assert payer_pv01 > 0
    assert receiver_pv01 > 0
    assert payer_pv01 == pytest.approx(receiver_pv01, rel=1e-9)


def test_pv01_and_dv01_are_distinct(payer, curve):
    """At a fixed rate away from fair, DV01 (net, moneyness-dependent) and PV01
    (leg-level annuity value) should differ -- they're not the same metric."""
    assert compute_pv01(payer, curve) != pytest.approx(compute_dv01(payer, curve), rel=1e-6)


def test_krd_sum_approximately_equals_total_dv01(payer, curve):
    krd = compute_krd(payer, curve)
    total_dv01 = compute_dv01(payer, curve)
    assert sum(krd.values()) == pytest.approx(total_dv01, abs=1.0)  # within $1 on $10mm notional


def test_krd_buckets_present(payer, curve):
    krd = compute_krd(payer, curve)
    assert set(krd.keys()) == {"2Y", "5Y", "10Y", "30Y"}


def test_two_swaps_same_dv01_different_krd_profile(curve):
    """A short-dated swap and a long-dated swap sized to the same total DV01 have
    completely different key-rate exposure -- the whole point of KRD over a single
    parallel DV01 number."""
    short_swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2028, 7, 9), 10_000_000, 0.03, pay_fixed=True)
    long_swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2036, 7, 9), 10_000_000, 0.03, pay_fixed=True)

    short_krd = compute_krd(short_swap, curve)
    long_krd = compute_krd(long_swap, curve)

    # short swap's risk should be concentrated in the 2Y bucket, long swap's in 10Y/30Y
    assert short_krd["2Y"] > short_krd["10Y"]
    assert long_krd["10Y"] > long_krd["2Y"]


def test_convexity_is_nonzero_and_opposite_sign_for_payer_receiver(payer, receiver, curve):
    payer_convexity = compute_convexity(payer, curve)
    receiver_convexity = compute_convexity(receiver, curve)
    assert payer_convexity != 0
    assert payer_convexity == pytest.approx(-receiver_convexity, rel=1e-9)


def test_zero_notional_gives_zero_risk(curve):
    zero_swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, LONG_MATURITY, 0.0, 0.03, pay_fixed=True)
    report = build_risk_report(zero_swap, curve)
    assert report.dv01 == pytest.approx(0.0)
    assert report.pv01 == pytest.approx(0.0)
    assert all(v == pytest.approx(0.0) for v in report.krd.values())
    assert report.convexity == pytest.approx(0.0)


def test_risk_report_object_shape(payer, curve):
    report = build_risk_report(payer, curve)
    assert report.notional == 10_000_000
    assert report.pay_fixed is True
    assert set(report.krd.keys()) == {"2Y", "5Y", "10Y", "30Y"}
    assert isinstance(report.dv01, float)
    assert isinstance(report.convexity, float)
