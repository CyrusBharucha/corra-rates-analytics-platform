import math

import numpy as np
import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve, reprice_par_bonds
from corra_pricer.curve_builder.shocked_curve import parallel_shift

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29


def _reprice_par_bonds(curve, yields_pct, tenor_years):
    return reprice_par_bonds(curve, yields_pct, tenor_years)


TENOR_YEARS = {"2Y": 2.0, "3Y": 3.0, "5Y": 5.0, "7Y": 7.0, "10Y": 10.0, "LONG": 30.0}


# --- 1. DF(0) = 1 ---
def test_df_at_zero_is_one():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    assert curve.discount_factor(0) == pytest.approx(1.0)


# --- 2. Discount factors strictly decreasing ---
def test_discount_factors_strictly_decreasing():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    ts = np.linspace(0.01, 30, 100)
    dfs = [curve.discount_factor(t) for t in ts]
    assert all(dfs[i] > dfs[i + 1] for i in range(len(dfs) - 1))


# --- 3. Zero rates finite ---
def test_zero_rates_finite():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    for t in np.linspace(0.01, 40, 50):
        z = curve.zero_rate(t)
        assert math.isfinite(z)


# --- 4. No negative discount factors ---
def test_no_negative_discount_factors():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    for t in np.linspace(0, 30, 50):
        assert curve.discount_factor(t) > 0


# --- 5. Bond reprices to par ---
def test_bonds_reprice_to_par():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    errors = _reprice_par_bonds(curve, NORMAL_YIELDS_PCT, TENOR_YEARS)
    for name, err in errors.items():
        assert abs(err) < 0.01, f"{name} mispriced by {err}"


# --- 5b. reprice_par_bonds: dedicated coverage for the extracted public function ---
def test_reprice_par_bonds_skips_missing_tenors():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    partial = dict(NORMAL_YIELDS_PCT)
    partial["10Y"] = None
    residuals = reprice_par_bonds(curve, partial, TENOR_YEARS)
    assert "10Y" not in residuals
    assert set(residuals.keys()) == {"2Y", "3Y", "5Y", "7Y", "LONG"}


def test_reprice_par_bonds_linear_matches_bootstraps_own_construction():
    """"linear" is the exact interpolation the bootstrap's internal gap
    solver assumes, so reprice_par_bonds() on a linear curve should match
    the bootstrap's own construction-time result almost exactly."""
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT, interpolation="linear")
    residuals = reprice_par_bonds(curve, NORMAL_YIELDS_PCT, TENOR_YEARS)
    for name, err in residuals.items():
        assert abs(err) < 0.01, f"linear/{name} mispriced by {err}"


def test_reprice_par_bonds_nonlinear_methods_stay_bounded():
    """log-linear-DF and cubic-spline curves are NOT what the bootstrap's
    internal gap solver assumed, so they can show a real, larger residual --
    most pronounced across the wide 10Y-to-30Y gap (confirmed: log-linear-DF
    mispricing the 30Y bond by ~$0.67 per $100 face is real, not a bug, and
    is itself useful diagnostic content for the dashboard). This just checks
    the divergence stays bounded/sane rather than blowing up."""
    for method in ["log_linear_df", "cubic_spline"]:
        curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT, interpolation=method)
        residuals = reprice_par_bonds(curve, NORMAL_YIELDS_PCT, TENOR_YEARS)
        for name, err in residuals.items():
            assert abs(err) < 2.0, f"{method}/{name} mispriced by {err}"


# --- 6. Curve monotonicity under a normal (upward-sloping) curve ---
def test_normal_curve_zero_rates_increasing():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    zeros = [curve.zero_rate(t) for t in [2, 3, 5, 7, 10, 30]]
    assert all(zeros[i] <= zeros[i + 1] + 1e-9 for i in range(len(zeros) - 1))


# --- 7. Inverted curve handled ---
def test_inverted_curve_handled():
    inverted = {"2Y": 5.00, "3Y": 4.70, "5Y": 4.30, "7Y": 4.00, "10Y": 3.70, "LONG": 3.50}
    curve = bootstrap_zero_curve(5.20, inverted)
    zeros = [curve.zero_rate(t) for t in [2, 3, 5, 7, 10, 30]]
    assert all(zeros[i] >= zeros[i + 1] - 1e-9 for i in range(len(zeros) - 1))
    errors = _reprice_par_bonds(curve, inverted, TENOR_YEARS)
    assert all(abs(e) < 0.01 for e in errors.values())


# --- 8. Flat curve handled ---
def test_flat_curve_handled():
    flat = {k: 3.00 for k in NORMAL_YIELDS_PCT}
    curve = bootstrap_zero_curve(3.00, flat)
    zeros = [curve.zero_rate(t) for t in [2, 3, 5, 7, 10, 30]]
    for z in zeros:
        assert z == pytest.approx(0.03, abs=5e-4)


# --- 9. Negative rate curve handled ---
def test_negative_rate_curve_handled():
    negative = {"2Y": -0.20, "3Y": -0.10, "5Y": 0.05, "7Y": 0.15, "10Y": 0.30, "LONG": 0.60}
    curve = bootstrap_zero_curve(-0.30, negative)
    for t in [2, 3, 5, 7, 10, 30]:
        assert math.isfinite(curve.zero_rate(t))
    errors = _reprice_par_bonds(curve, negative, TENOR_YEARS)
    assert all(abs(e) < 0.01 for e in errors.values())


# --- 10. Extreme steepener handled ---
def test_extreme_steepener_handled():
    steep = {"2Y": 0.50, "3Y": 1.00, "5Y": 2.50, "7Y": 4.00, "10Y": 6.00, "LONG": 9.00}
    curve = bootstrap_zero_curve(0.30, steep)
    zeros = [curve.zero_rate(t) for t in [2, 5, 10, 30]]
    assert zeros[0] < zeros[-1]
    assert all(math.isfinite(z) for z in zeros)


# --- 11. Extreme flattener handled ---
def test_extreme_flattener_handled():
    flattener = {"2Y": 6.00, "3Y": 5.50, "5Y": 4.50, "7Y": 4.00, "10Y": 3.80, "LONG": 3.75}
    curve = bootstrap_zero_curve(6.20, flattener)
    zeros = [curve.zero_rate(t) for t in [2, 5, 10, 30]]
    assert zeros[0] > zeros[-1]
    assert all(math.isfinite(z) for z in zeros)


# --- 12. 100bp parallel shift reprices correctly ---
def test_100bp_parallel_shift_reprices():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    shifted = parallel_shift(curve, 100)
    for t in [2, 5, 10, 30]:
        assert shifted.zero_rate(t) == pytest.approx(curve.zero_rate(t) + 0.01, abs=1e-9)
        assert shifted.discount_factor(t) < curve.discount_factor(t)


# --- 13. 500bp stress survives ---
def test_500bp_stress_survives():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    shifted = parallel_shift(curve, 500)
    for t in [2, 5, 10, 30]:
        assert math.isfinite(shifted.zero_rate(t))
        assert 0 < shifted.discount_factor(t) < 1


# --- 14. 1000bp stress survives ---
def test_1000bp_stress_survives():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    shifted_up = parallel_shift(curve, 1000)
    shifted_down = parallel_shift(curve, -1000)
    for t in [2, 5, 10, 30]:
        assert math.isfinite(shifted_up.zero_rate(t))
        assert math.isfinite(shifted_down.zero_rate(t))
        assert 0 < shifted_up.discount_factor(t) < 1


# --- 15. Long-end extrapolation stable ---
def test_long_end_extrapolation_stable():
    curve = bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)
    z_at_node = curve.zero_rate(30)
    for t in [35, 40, 50, 100]:
        z = curve.zero_rate(t)
        assert math.isfinite(z)
        assert z == pytest.approx(z_at_node, abs=1e-9)  # flat extrapolation beyond last node
