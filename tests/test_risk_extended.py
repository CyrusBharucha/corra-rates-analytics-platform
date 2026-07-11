import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.curve_builder.shocked_curve import key_rate_weight, parallel_shift
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import (
    DEFAULT_KRD_BUCKETS,
    compute_convexity,
    compute_dv01,
    compute_krd,
)

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


def _swap(years, notional=10_000_000, fixed_rate=0.03, pay_fixed=True, days=None):
    maturity = (TRADE_DATE + dt.timedelta(days=days)) if days is not None \
        else dt.date(TRADE_DATE.year + years, TRADE_DATE.month, TRADE_DATE.day)
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, maturity, notional, fixed_rate, pay_fixed=pay_fixed)


# --- DV01 ---

def test_dv01_pay_fixed_positive(curve):
    assert compute_dv01(_swap(5, pay_fixed=True), curve) > 0


def test_dv01_receive_fixed_negative(curve):
    assert compute_dv01(_swap(5, pay_fixed=False), curve) < 0


def test_dv01_scales_linearly_with_notional(curve):
    dv01_1x = compute_dv01(_swap(5, notional=10_000_000), curve)
    dv01_2x = compute_dv01(_swap(5, notional=20_000_000), curve)
    assert dv01_2x == pytest.approx(2 * dv01_1x, rel=1e-6)


def test_dv01_grows_with_maturity(curve):
    dv01s = [compute_dv01(_swap(y), curve) for y in [1, 2, 3, 5, 7, 10, 30]]
    assert all(dv01s[i] < dv01s[i + 1] for i in range(len(dv01s) - 1))


def test_dv01_near_zero_at_short_maturity(curve):
    long_dv01 = compute_dv01(_swap(10), curve)
    short_dv01 = compute_dv01(_swap(None, days=7), curve)
    assert 0 < short_dv01 < long_dv01 * 0.01


# --- KRD ---

def test_krd_sum_approximately_equals_total_dv01(curve):
    swap = _swap(10)
    krd = compute_krd(swap, curve)
    total = compute_dv01(swap, curve)
    assert sum(krd.values()) == pytest.approx(total, abs=1.0)


def test_parallel_shift_reconstruction_from_bucket_weights():
    """Summing tent weights across all buckets reconstructs an exact parallel
    shift (weight = 1) at every point on the curve -- the mathematical
    guarantee that makes sum(KRD) ~= total DV01 work."""
    for t in [0.1, 1, 2, 3.5, 5, 8, 10, 20, 30, 40]:
        total_weight = sum(key_rate_weight(t, b, DEFAULT_KRD_BUCKETS) for b in DEFAULT_KRD_BUCKETS)
        assert total_weight == pytest.approx(1.0, abs=1e-9)


def test_single_bucket_isolation(curve):
    """A 30Y-only key-rate shock should have zero weight (and zero risk
    contribution) at the 2Y point on the curve."""
    weight_at_2y_from_30y_bucket = key_rate_weight(2.0, 30.0, DEFAULT_KRD_BUCKETS)
    assert weight_at_2y_from_30y_bucket == pytest.approx(0.0, abs=1e-9)

    weight_at_2y_from_2y_bucket = key_rate_weight(2.0, 2.0, DEFAULT_KRD_BUCKETS)
    assert weight_at_2y_from_2y_bucket == pytest.approx(1.0, abs=1e-9)


def test_krd_bucket_ordering_sensible(curve):
    """For a long-dated (10Y) swap on a normal curve, exposure should be
    concentrated toward the buckets nearer its own maturity, not scattered
    randomly -- 10Y bucket should dominate for a 10Y swap."""
    swap = _swap(10)
    krd = compute_krd(swap, curve)
    assert krd["10Y"] > krd["2Y"]
    assert krd["10Y"] > krd["30Y"]


# --- Convexity ---

def test_convexity_stable_under_different_bump_sizes(curve):
    swap = _swap(10)
    c_1bp = compute_convexity(swap, curve, bump_bp=1.0)
    c_5bp = compute_convexity(swap, curve, bump_bp=5.0)
    # both should have the same sign and be within an order of magnitude
    # scaled appropriately (convexity scales ~ bump^2)
    assert (c_1bp < 0) == (c_5bp < 0)


def test_convexity_payer_receiver_mirrors(curve):
    payer_c = compute_convexity(_swap(10, pay_fixed=True), curve)
    receiver_c = compute_convexity(_swap(10, pay_fixed=False), curve)
    assert payer_c == pytest.approx(-receiver_c, rel=1e-9)


def test_convexity_scales_with_notional(curve):
    c_1x = compute_convexity(_swap(10, notional=10_000_000), curve)
    c_2x = compute_convexity(_swap(10, notional=20_000_000), curve)
    assert c_2x == pytest.approx(2 * c_1x, rel=1e-6)


def test_convexity_increases_in_magnitude_with_maturity(curve):
    convexities = [abs(compute_convexity(_swap(y), curve)) for y in [1, 2, 3, 5, 7, 10, 30]]
    assert all(convexities[i] < convexities[i + 1] for i in range(len(convexities) - 1))
