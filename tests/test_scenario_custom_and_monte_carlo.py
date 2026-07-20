import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.scenario_engine.scenario_engine import (
    run_custom_scenario,
    run_monte_carlo_scenarios,
    run_scenario,
)
from corra_pricer.scenario_engine.scenarios import (
    CURVE_TRADE_SCENARIOS,
    MACRO_SCENARIOS,
    PARALLEL_SCENARIOS,
    SCENARIO_CATALOG,
)

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


@pytest.fixture
def swap():
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2036, 7, 9), 10_000_000, 0.03, pay_fixed=True)


# --- Catalog scale ---

def test_catalog_has_at_least_40_scenarios():
    assert len(SCENARIO_CATALOG) >= 40


def test_catalog_spans_all_three_categories():
    assert len(PARALLEL_SCENARIOS) >= 10
    assert len(CURVE_TRADE_SCENARIOS) >= 10
    assert len(MACRO_SCENARIOS) >= 10


def test_parallel_scenarios_cover_expected_magnitudes():
    for bp in [1, 5, 10, 25, 50, 100, 200]:
        assert f"parallel_+{bp}bp" in SCENARIO_CATALOG
        assert f"parallel_-{bp}bp" in SCENARIO_CATALOG


def test_new_curve_shapes_present():
    for name in ["bear_steepener", "bull_steepener", "bear_flattener", "bull_flattener",
                  "twist", "butterfly", "humped", "inverted"]:
        assert name in SCENARIO_CATALOG
        assert SCENARIO_CATALOG[name].category == "curve_trade"


# --- Custom scenario / catalog refactor equivalence ---

def test_custom_scenario_matches_catalog_scenario_with_same_shocks(swap, curve):
    """Proves the run_scenario/run_custom_scenario refactor didn't change
    behavior -- feeding run_custom_scenario the exact shocks of a catalog
    entry must reproduce that catalog scenario's result exactly."""
    catalog_result = run_scenario(swap, curve, "recession")
    custom_result = run_custom_scenario(
        swap, curve, SCENARIO_CATALOG["recession"].bucket_shocks_bp, name="recession_custom",
    )
    assert custom_result.npv_change == pytest.approx(catalog_result.npv_change, rel=1e-12)
    assert custom_result.dv01_change == pytest.approx(catalog_result.dv01_change, rel=1e-12)
    assert custom_result.category == "user_defined"


def test_custom_scenario_arbitrary_shock(swap, curve):
    result = run_custom_scenario(swap, curve, {2.0: 10, 5.0: -5}, name="my_custom_trade")
    assert result.scenario_name == "my_custom_trade"
    assert result.category == "user_defined"
    assert "2Y" in result.pnl_attribution_bp
    assert "10Y" in result.pnl_attribution_bp  # buckets with no shock still appear, at 0


def test_custom_scenario_no_shock_leaves_npv_unchanged(swap, curve):
    result = run_custom_scenario(swap, curve, {}, name="no_shock")
    assert result.npv_change == pytest.approx(0.0)


# --- Monte Carlo ---

def test_monte_carlo_returns_requested_number_of_rows(swap, curve):
    mc = run_monte_carlo_scenarios(swap, curve, n_simulations=50, shock_std_bp=25, seed=1)
    assert len(mc) == 50


def test_monte_carlo_columns_present(swap, curve):
    mc = run_monte_carlo_scenarios(swap, curve, n_simulations=10, shock_std_bp=25, seed=1)
    for col in ["simulation", "npv_change", "dv01_change", "2Y_shock_bp", "5Y_shock_bp",
                "10Y_shock_bp", "30Y_shock_bp"]:
        assert col in mc.columns


def test_monte_carlo_reproducible_with_same_seed(swap, curve):
    mc1 = run_monte_carlo_scenarios(swap, curve, n_simulations=30, shock_std_bp=25, seed=42)
    mc2 = run_monte_carlo_scenarios(swap, curve, n_simulations=30, shock_std_bp=25, seed=42)
    assert (mc1["npv_change"] == mc2["npv_change"]).all()


def test_monte_carlo_varies_with_different_seed(swap, curve):
    mc1 = run_monte_carlo_scenarios(swap, curve, n_simulations=30, shock_std_bp=25, seed=42)
    mc2 = run_monte_carlo_scenarios(swap, curve, n_simulations=30, shock_std_bp=25, seed=99)
    assert not (mc1["npv_change"] == mc2["npv_change"]).all()


def test_monte_carlo_zero_std_gives_zero_pnl(swap, curve):
    """A shock std of 0 means every simulation draws a shock of exactly 0 --
    NPV change should be exactly 0 for every row."""
    mc = run_monte_carlo_scenarios(swap, curve, n_simulations=20, shock_std_bp=0.0, seed=1)
    assert mc["npv_change"].abs().max() < 1e-9


def test_monte_carlo_wider_std_gives_wider_pnl_distribution(swap, curve):
    narrow = run_monte_carlo_scenarios(swap, curve, n_simulations=300, shock_std_bp=5, seed=7)
    wide = run_monte_carlo_scenarios(swap, curve, n_simulations=300, shock_std_bp=100, seed=7)
    assert wide["npv_change"].std() > narrow["npv_change"].std()
