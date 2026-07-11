import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import compute_dv01
from corra_pricer.scenario_engine.scenario_engine import (
    build_scenario_curve,
    run_all_scenarios,
    run_scenario,
    scenario_summary_table,
)
from corra_pricer.scenario_engine.scenarios import SCENARIO_CATALOG

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


def _swap(years, pay_fixed=True, notional=10_000_000, fixed_rate=0.03):
    maturity = dt.date(TRADE_DATE.year + years, TRADE_DATE.month, TRADE_DATE.day)
    return CorraOISSwap(TRADE_DATE, TRADE_DATE, maturity, notional, fixed_rate, pay_fixed=pay_fixed)


# --- Catalog completeness ---

def test_catalog_has_all_required_scenarios():
    required = {
        "parallel_+25bp", "parallel_-25bp", "parallel_+50bp", "parallel_-50bp",
        "2s10s_steepener", "2s10s_flattener", "5s30s_steepener", "5s30s_flattener",
        "boc_surprise_hike", "boc_surprise_cut", "inflation_shock", "recession",
    }
    assert required.issubset(SCENARIO_CATALOG.keys())


def test_unknown_scenario_raises(curve):
    swap = _swap(5)
    with pytest.raises(KeyError):
        run_scenario(swap, curve, "not_a_real_scenario")


# --- Parallel shifts ---

def test_parallel_plus_25bp_equals_true_parallel_dv01(curve):
    """A +25bp scenario built from stacked key-rate tents should match an
    exact parallel_shift, since the tents partition to 1 at every point."""
    from corra_pricer.curve_builder.shocked_curve import parallel_shift
    swap = _swap(10)
    scenario_curve = build_scenario_curve(curve, SCENARIO_CATALOG["parallel_+25bp"])
    true_parallel = parallel_shift(curve, 25)
    for t in [1, 2, 5, 10, 20, 30]:
        assert scenario_curve.zero_rate(t) == pytest.approx(true_parallel.zero_rate(t), abs=1e-9)


def test_parallel_up_helps_payer_hurts_receiver(curve):
    payer = _swap(10, pay_fixed=True)
    receiver = _swap(10, pay_fixed=False)
    payer_result = run_scenario(payer, curve, "parallel_+25bp")
    receiver_result = run_scenario(receiver, curve, "parallel_+25bp")
    assert payer_result.npv_change > 0
    assert receiver_result.npv_change < 0


def test_1bp_scenario_matches_dv01(curve):
    """The +1bp parallel scenario's NPV change should closely match the
    risk engine's DV01 (they're computing the same thing two different ways)."""
    swap = _swap(10)
    dv01 = compute_dv01(swap, curve)
    result = run_scenario(swap, curve, "parallel_+1bp")
    assert result.npv_change == pytest.approx(dv01, abs=0.5)


# --- Curve trades ---

def test_2s10s_steepener_hurts_short_payer_helps_long_payer(curve):
    short_payer = _swap(2)
    long_payer = _swap(10)
    short_result = run_scenario(short_payer, curve, "2s10s_steepener")
    long_result = run_scenario(long_payer, curve, "2s10s_steepener")
    assert short_result.npv_change < 0  # 2Y rate falls -> hurts a 2Y payer
    assert long_result.npv_change > 0   # 10Y rate rises -> helps a 10Y payer


def test_2s10s_flattener_is_approximately_mirror_of_steepener(curve):
    """Steepener and flattener are equal-and-opposite bucket shocks, so under
    a *linear* (DV01/KRD) approximation their P&L would be exact mirrors.
    The true, fully repriced NPV changes differ slightly because the swap has
    convexity (see test_risk_extended.py) -- a +12.5bp move and a -12.5bp
    move on a convex instrument are never perfectly symmetric. This checks
    they're close (same order of magnitude, opposite sign) without asserting
    the false exact symmetry a linear model would predict."""
    swap = _swap(10)
    steepener = run_scenario(swap, curve, "2s10s_steepener")
    flattener = run_scenario(swap, curve, "2s10s_flattener")
    assert steepener.npv_change == pytest.approx(-flattener.npv_change, rel=0.03)  # within 3%
    assert (steepener.npv_change > 0) != (flattener.npv_change > 0)


def test_5s30s_steepener_hurts_5y_payer_helps_30y_payer(curve):
    five_payer = _swap(5)
    thirty_payer = _swap(30)
    five_result = run_scenario(five_payer, curve, "5s30s_steepener")
    thirty_result = run_scenario(thirty_payer, curve, "5s30s_steepener")
    assert five_result.npv_change < 0
    assert thirty_result.npv_change > 0


# --- Macro events ---

def test_boc_surprise_hike_helps_payer(curve):
    swap = _swap(10, pay_fixed=True)
    result = run_scenario(swap, curve, "boc_surprise_hike")
    assert result.npv_change > 0


def test_boc_surprise_cut_hurts_payer(curve):
    swap = _swap(10, pay_fixed=True)
    result = run_scenario(swap, curve, "boc_surprise_cut")
    assert result.npv_change < 0


def test_boc_surprise_hike_and_cut_are_approximately_mirrors(curve):
    """Same convexity caveat as the steepener/flattener pair above: exact
    mirror symmetry only holds for the linear approximation, not the true
    reprice."""
    swap = _swap(10)
    hike = run_scenario(swap, curve, "boc_surprise_hike")
    cut = run_scenario(swap, curve, "boc_surprise_cut")
    assert hike.npv_change == pytest.approx(-cut.npv_change, rel=0.03)  # within 3%
    assert (hike.npv_change > 0) != (cut.npv_change > 0)


def test_inflation_shock_hits_long_end_payer_harder_than_short(curve):
    short_payer = _swap(2)
    long_payer = _swap(10)
    short_result = run_scenario(short_payer, curve, "inflation_shock")
    long_result = run_scenario(long_payer, curve, "inflation_shock")
    # normalize by DV01 so we're comparing shape sensitivity, not just size
    short_sensitivity = short_result.npv_change / compute_dv01(short_payer, curve)
    long_sensitivity = long_result.npv_change / compute_dv01(long_payer, curve)
    assert long_sensitivity > short_sensitivity


def test_recession_is_largest_magnitude_macro_scenario(curve):
    swap = _swap(10, pay_fixed=True)
    recession = run_scenario(swap, curve, "recession")
    hike = run_scenario(swap, curve, "boc_surprise_hike")
    cut = run_scenario(swap, curve, "boc_surprise_cut")
    inflation = run_scenario(swap, curve, "inflation_shock")
    assert abs(recession.npv_change) > abs(hike.npv_change)
    assert abs(recession.npv_change) > abs(cut.npv_change)
    assert abs(recession.npv_change) >= abs(inflation.npv_change)


# --- PnL attribution ---

def test_pnl_attribution_approximately_matches_full_reprice(curve):
    """The KRD-based linear attribution should be close to (but not
    necessarily exactly equal to) the true, fully repriced NPV change --
    the gap is the convexity/cross-term residual."""
    swap = _swap(10)
    result = run_scenario(swap, curve, "parallel_+25bp")
    assert result.attribution_total == pytest.approx(result.npv_change, rel=0.02)  # within 2%


def test_pnl_attribution_residual_grows_with_shock_size(curve):
    """Bigger shocks -> bigger convexity effect -> bigger (in absolute terms)
    linear-attribution residual."""
    swap = _swap(10)
    small = run_scenario(swap, curve, "parallel_+1bp")
    large = run_scenario(swap, curve, "recession")
    assert abs(large.attribution_residual) > abs(small.attribution_residual)


def test_pnl_attribution_buckets_match_shocked_buckets(curve):
    swap = _swap(10)
    result = run_scenario(swap, curve, "2s10s_steepener")
    assert result.pnl_attribution_bp["5Y"] == pytest.approx(0.0, abs=1e-9)
    assert result.pnl_attribution_bp["30Y"] == pytest.approx(0.0, abs=1e-9)
    assert result.pnl_attribution_bp["2Y"] != 0.0
    assert result.pnl_attribution_bp["10Y"] != 0.0


# --- DV01 change reporting ---

def test_dv01_change_reported_and_finite(curve):
    swap = _swap(10)
    result = run_scenario(swap, curve, "recession")
    assert result.dv01_after == pytest.approx(result.dv01_before + result.dv01_change, abs=1e-6)


# --- Batch run / summary ---

def test_run_all_scenarios_covers_full_catalog(curve):
    swap = _swap(10)
    results = run_all_scenarios(swap, curve)
    assert len(results) == len(SCENARIO_CATALOG)
    names = {r.scenario_name for r in results}
    assert names == set(SCENARIO_CATALOG.keys())


def test_scenario_summary_table_shape(curve):
    swap = _swap(10)
    table = scenario_summary_table(swap, curve)
    assert len(table) == len(SCENARIO_CATALOG)
    assert "npv_change" in table.columns
    assert "dv01_change" in table.columns
