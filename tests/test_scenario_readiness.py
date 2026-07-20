import numpy as np
import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.curve_builder.shocked_curve import key_rate_shift, parallel_shift

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


# --- Parallel shift wrapper works ---

def test_parallel_shift_wrapper_works(curve):
    shifted = parallel_shift(curve, 25)
    for t in [0.5, 2, 5, 10, 30]:
        assert shifted.zero_rate(t) == pytest.approx(curve.zero_rate(t) + 0.0025, abs=1e-9)


# --- Node shifts work ---

def test_single_node_shift_works(curve):
    shifted = curve.with_node_shifts({5.0: 10})  # +10bp on the 5Y node only
    assert shifted.zero_rate(5.0) == pytest.approx(curve.zero_rate(5.0) + 0.0010, abs=1e-9)
    assert shifted.zero_rate(2.0) == pytest.approx(curve.zero_rate(2.0), abs=1e-9)


# --- Multiple node shifts work ---

def test_multiple_node_shifts_work(curve):
    shifted = curve.with_node_shifts({2.0: 5, 10.0: -3})
    assert shifted.zero_rate(2.0) == pytest.approx(curve.zero_rate(2.0) + 0.0005, abs=1e-9)
    assert shifted.zero_rate(10.0) == pytest.approx(curve.zero_rate(10.0) - 0.0003, abs=1e-9)
    assert shifted.zero_rate(5.0) == pytest.approx(curve.zero_rate(5.0), abs=1e-9)  # untouched


# --- Sequential shifts commute ---

def test_sequential_parallel_shifts_commute(curve):
    order_a = parallel_shift(parallel_shift(curve, 10), 20)
    order_b = parallel_shift(parallel_shift(curve, 20), 10)
    for t in [1, 5, 10, 30]:
        assert order_a.zero_rate(t) == pytest.approx(order_b.zero_rate(t), abs=1e-12)


def test_sequential_key_rate_shifts_commute(curve):
    buckets = [2.0, 5.0, 10.0, 30.0]
    order_a = key_rate_shift(key_rate_shift(curve, 5.0, 10, buckets), 10.0, 5, buckets)
    order_b = key_rate_shift(key_rate_shift(curve, 10.0, 5, buckets), 5.0, 10, buckets)
    for t in [1, 3, 5, 7, 10, 20, 30]:
        assert order_a.zero_rate(t) == pytest.approx(order_b.zero_rate(t), abs=1e-12)


# --- Shock removal restores original curve (base curve immutability) ---

def test_base_curve_unmodified_by_parallel_shift(curve):
    original_zeros = curve.zero_rates.copy()
    _ = parallel_shift(curve, 500)
    assert np.array_equal(curve.zero_rates, original_zeros)


def test_base_curve_unmodified_by_node_shift(curve):
    original_zeros = curve.zero_rates.copy()
    _ = curve.with_node_shifts({5.0: 100})
    assert np.array_equal(curve.zero_rates, original_zeros)


def test_discarding_shocked_curve_leaves_base_queryable_unchanged(curve):
    baseline = curve.zero_rate(5.0)
    shocked = parallel_shift(curve, 50)
    del shocked
    assert curve.zero_rate(5.0) == pytest.approx(baseline, abs=1e-12)


def test_zero_bump_shift_is_identity(curve):
    shifted = parallel_shift(curve, 0)
    for t in [1, 5, 10, 30]:
        assert shifted.zero_rate(t) == pytest.approx(curve.zero_rate(t), abs=1e-12)
