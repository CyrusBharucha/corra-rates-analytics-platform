"""
Interpolation methods for the zero-rate curve.

All interpolators take curve nodes (times in years, zero rates in decimal,
continuously compounded) and return a callable time -> zero rate.
Flat extrapolation is used outside the node range, which is standard
market practice.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline


def _clip_to_range(t: float, times: np.ndarray) -> float:
    return min(max(t, times[0]), times[-1])


def linear_zero_interpolator(times: np.ndarray, zero_rates: np.ndarray):
    times = np.asarray(times, dtype=float)
    zero_rates = np.asarray(zero_rates, dtype=float)

    def interp(t: float) -> float:
        tc = _clip_to_range(t, times)
        return float(np.interp(tc, times, zero_rates))

    return interp


def log_linear_df_interpolator(times: np.ndarray, zero_rates: np.ndarray):
    """Interpolates linearly on log(discount factor), i.e. log-linear on DF.
    This is equivalent to piecewise-constant instantaneous forward rates.
    """
    times = np.asarray(times, dtype=float)
    zero_rates = np.asarray(zero_rates, dtype=float)
    log_dfs = -zero_rates * times

    def interp(t: float) -> float:
        tc = _clip_to_range(t, times)
        log_df = float(np.interp(tc, times, log_dfs))
        if tc == 0:
            return float(zero_rates[0])
        return -log_df / tc

    return interp


def cubic_spline_interpolator(times: np.ndarray, zero_rates: np.ndarray):
    times = np.asarray(times, dtype=float)
    zero_rates = np.asarray(zero_rates, dtype=float)
    spline = CubicSpline(times, zero_rates, bc_type="natural")

    def interp(t: float) -> float:
        tc = _clip_to_range(t, times)
        return float(spline(tc))

    return interp


INTERPOLATORS = {
    "linear": linear_zero_interpolator,
    "log_linear_df": log_linear_df_interpolator,
    "cubic_spline": cubic_spline_interpolator,
}
