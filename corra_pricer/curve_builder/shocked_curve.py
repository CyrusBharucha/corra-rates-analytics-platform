"""
ShockedCurve: wraps a base YieldCurve with an additive, continuous zero-rate
shock function of time. This is what makes bump-and-reprice risk correct:
a shock must apply at every query time the pricer touches (payment dates,
leg start/end), not just at the curve's discrete bootstrap nodes -- a swap's
cashflow dates rarely land exactly on a curve node.

Used by risk_engine.py for parallel shifts (DV01, convexity) and key-rate
shifts (KRD), via the two factory functions below.
"""
from __future__ import annotations

from typing import Callable

import numpy as np


class ShockedCurve:
    """Duck-types the parts of YieldCurve's interface the pricer needs
    (zero_rate, discount_factor) without rebuilding/reinterpolating nodes."""

    def __init__(self, base_curve, shock_fn: Callable[[float], float], label: str):
        self.base_curve = base_curve
        self.shock_fn = shock_fn
        self.label = label

    def zero_rate(self, t: float) -> float:
        if t <= 0:
            return self.base_curve.zero_rate(0) + self.shock_fn(0)
        return self.base_curve.zero_rate(t) + self.shock_fn(t)

    def discount_factor(self, t: float) -> float:
        if t <= 0:
            return 1.0
        return float(np.exp(-self.zero_rate(t) * t))


def parallel_shift(curve, bump_bp: float, label: str | None = None) -> ShockedCurve:
    """Shifts the zero rate by bump_bp at every maturity -- a true parallel shift,
    unlike YieldCurve.with_parallel_shift which only moves the discrete nodes
    (and therefore only approximately parallel-shifts interpolated points)."""
    shock = bump_bp / 10_000.0
    return ShockedCurve(curve, lambda t: shock, label or f"{curve.label}_parallel_{bump_bp:+g}bp")


def key_rate_weight(t: float, bucket_time: float, buckets: list[float]) -> float:
    """Triangular ('tent') key-rate weight, standard Ho (1992) / Reitano construction:
    weight = 1 exactly at bucket_time, decays linearly to 0 at the neighbouring
    buckets, and is held flat (1 or 0) beyond the first/last bucket. By
    construction, sum(weight(t, b, buckets) for b in buckets) == 1 for every t,
    so shocking every bucket simultaneously reconstructs an exact parallel shift.
    This is why sum(KRDs) ~= total DV01.
    """
    buckets = sorted(buckets)
    idx = buckets.index(bucket_time)
    left = buckets[idx - 1] if idx > 0 else None
    right = buckets[idx + 1] if idx < len(buckets) - 1 else None

    if t <= bucket_time:
        if left is None:
            return 1.0  # flat left of the first bucket
        if t <= left:
            return 0.0
        return (t - left) / (bucket_time - left)
    else:
        if right is None:
            return 1.0  # flat right of the last bucket
        if t >= right:
            return 0.0
        return (right - t) / (right - bucket_time)


def key_rate_shift(curve, bucket_time: float, bump_bp: float, buckets: list[float],
                    label: str | None = None) -> ShockedCurve:
    shock_size = bump_bp / 10_000.0

    def shock_fn(t: float, bucket_time=bucket_time, buckets=buckets, shock_size=shock_size) -> float:
        return key_rate_weight(t, bucket_time, buckets) * shock_size

    return ShockedCurve(curve, shock_fn, label or f"{curve.label}_krd_{bucket_time:g}Y_{bump_bp:+g}bp")
