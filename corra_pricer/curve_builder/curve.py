"""
YieldCurve: the object every other module (pricing, risk, scenario) consumes.

Internally, the curve is represented as a set of (time, continuously-compounded
zero rate) nodes plus a chosen interpolation method. All discounting is done
via DF(t) = exp(-z(t) * t).
"""
from __future__ import annotations

import numpy as np

from corra_pricer.curve_builder.interpolation import INTERPOLATORS


class YieldCurve:
    def __init__(
        self,
        times: np.ndarray,
        zero_rates: np.ndarray,
        interpolation: str = "linear",
        label: str = "curve",
    ):
        if interpolation not in INTERPOLATORS:
            raise ValueError(f"Unknown interpolation method '{interpolation}'. "
                              f"Choose from {list(INTERPOLATORS)}.")
        self.times = np.asarray(times, dtype=float)
        self.zero_rates = np.asarray(zero_rates, dtype=float)
        self.interpolation = interpolation
        self.label = label
        self._interp = INTERPOLATORS[interpolation](self.times, self.zero_rates)

    def zero_rate(self, t: float) -> float:
        """Continuously-compounded zero rate for maturity t (in years)."""
        if t <= 0:
            return float(self.zero_rates[0])
        return self._interp(t)

    def discount_factor(self, t: float) -> float:
        if t <= 0:
            return 1.0
        return float(np.exp(-self.zero_rate(t) * t))

    def forward_rate(self, t1: float, t2: float) -> float:
        """Simple annualized forward rate between t1 and t2 (t2 > t1)."""
        if t2 <= t1:
            raise ValueError("t2 must be greater than t1")
        df1 = self.discount_factor(t1)
        df2 = self.discount_factor(t2)
        return (df1 / df2 - 1.0) / (t2 - t1)

    def with_parallel_shift(self, shift_bp: float, label: str | None = None) -> "YieldCurve":
        """Returns a new curve with every node shifted by shift_bp basis points."""
        shifted = self.zero_rates + shift_bp / 10_000.0
        return YieldCurve(
            self.times, shifted, interpolation=self.interpolation,
            label=label or f"{self.label}_shift_{shift_bp:+g}bp",
        )

    def with_node_shifts(self, shifts_bp: dict[float, float], label: str | None = None) -> "YieldCurve":
        """shifts_bp: {node_time: shift_in_bp}. Only exact node times are shifted directly;
        use bucketed key-rate shocks in the risk engine for shocks at arbitrary tenors."""
        shifted = self.zero_rates.copy()
        for i, t in enumerate(self.times):
            for node_t, bp in shifts_bp.items():
                if np.isclose(t, node_t):
                    shifted[i] += bp / 10_000.0
        return YieldCurve(
            self.times, shifted, interpolation=self.interpolation,
            label=label or f"{self.label}_node_shift",
        )

    def as_dataframe(self):
        import pandas as pd
        return pd.DataFrame({
            "tenor_years": self.times,
            "zero_rate_pct": self.zero_rates * 100,
            "discount_factor": [self.discount_factor(t) for t in self.times],
        })
