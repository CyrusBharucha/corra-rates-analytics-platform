import math

import numpy as np
import pytest

from corra_pricer.curve_builder.curve import YieldCurve
from corra_pricer.curve_builder.interpolation import INTERPOLATORS

NODE_TIMES = np.array([0.00274, 2.0, 3.0, 5.0, 7.0, 10.0, 30.0])
NODE_ZEROS = np.array([0.0229, 0.0278, 0.0290, 0.0311, 0.0326, 0.0354, 0.0407])

METHODS = list(INTERPOLATORS.keys())


@pytest.mark.parametrize("method", METHODS)
def test_exact_node_matching(method):
    curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    for t, z in zip(NODE_TIMES, NODE_ZEROS):
        assert curve.zero_rate(t) == pytest.approx(z, abs=1e-8)


@pytest.mark.parametrize("method", METHODS)
def test_continuity_no_jumps(method):
    """Zero rate shouldn't jump discontinuously for a tiny step in t."""
    curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    eps = 1e-4
    for t in np.linspace(0.5, 29.5, 30):
        z1 = curve.zero_rate(t)
        z2 = curve.zero_rate(t + eps)
        assert abs(z2 - z1) < 0.01, f"jump at t={t} for {method}: {z1} -> {z2}"


@pytest.mark.parametrize("method", METHODS)
def test_forward_rates_finite(method):
    curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    for t1, t2 in [(0.5, 1.0), (2.0, 5.0), (10.0, 30.0), (29.0, 30.0)]:
        fwd = curve.forward_rate(t1, t2)
        assert math.isfinite(fwd)


@pytest.mark.parametrize("method", METHODS)
def test_flat_extrapolation_beyond_last_node(method):
    curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    z_last = curve.zero_rate(30.0)
    for t in [31, 40, 100]:
        assert curve.zero_rate(t) == pytest.approx(z_last, abs=1e-8)


@pytest.mark.parametrize("method", METHODS)
def test_flat_extrapolation_before_first_node(method):
    curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    z_first = curve.zero_rate(NODE_TIMES[0])
    assert curve.zero_rate(0.0001) == pytest.approx(z_first, abs=1e-8)


@pytest.mark.parametrize("method", METHODS)
def test_interpolation_ordering_matches_node_trend(method):
    """Between two adjacent nodes on this upward-sloping curve, interpolated
    values should stay within the [lower_node, upper_node] envelope (no
    wild overshoot for a well-behaved, monotonic input curve)."""
    curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    for i in range(len(NODE_TIMES) - 1):
        t_lo, t_hi = NODE_TIMES[i], NODE_TIMES[i + 1]
        z_lo, z_hi = NODE_ZEROS[i], NODE_ZEROS[i + 1]
        mid = (t_lo + t_hi) / 2
        z_mid = curve.zero_rate(mid)
        # allow a small tolerance for cubic spline overshoot
        assert min(z_lo, z_hi) - 1e-3 <= z_mid <= max(z_lo, z_hi) + 1e-3


@pytest.mark.parametrize("method", METHODS)
def test_small_perturbation_stability(method):
    """A 0.1bp perturbation to one node shouldn't cause a wild swing in
    interpolated values far from that node."""
    perturbed_zeros = NODE_ZEROS.copy()
    perturbed_zeros[3] += 0.00001  # 0.1bp bump on the 5Y node
    base_curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
    perturbed_curve = YieldCurve(NODE_TIMES, perturbed_zeros, interpolation=method)
    far_t = 30.0
    assert abs(perturbed_curve.zero_rate(far_t) - base_curve.zero_rate(far_t)) < 1e-4


def test_all_methods_agree_closely_between_nodes():
    """Different interpolation methods should stay in the same ballpark on a
    smooth, normal curve -- a sanity check that none of the three
    implementations has a gross bug (wrong sign, wrong magnitude, etc).
    Note: t=1.0 sits in the long, sparse first segment (ON node at ~0 to the
    2Y node), where log-linear-DF (which is linear in z*t, not z) and
    linear-on-zero-rate genuinely diverge by tens of bp -- that's expected
    methodology divergence, not a bug, so the tolerance here is loose enough
    to allow it while still catching a real implementation defect."""
    curves = {m: YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=m) for m in METHODS}
    for t in [1.0, 4.0, 6.0, 8.5, 20.0]:
        values = [c.zero_rate(t) for c in curves.values()]
        assert max(values) - min(values) < 0.005  # within 50bp of each other


def test_discount_factors_consistent_with_zero_rates():
    for method in METHODS:
        curve = YieldCurve(NODE_TIMES, NODE_ZEROS, interpolation=method)
        for t in [1, 5, 10, 20]:
            expected_df = math.exp(-curve.zero_rate(t) * t)
            assert curve.discount_factor(t) == pytest.approx(expected_df, rel=1e-9)
