"""
The ONLY module in the dashboard that touches corra_pricer's backend
directly. Every page imports from here (plus charts.py/tables.py for pure
presentation) -- nothing in pages/ calls market_data, curve_builder,
pricing_engine, risk_engine, scenario_engine, or analytics directly, and
nothing here re-implements any of their math. This module's only job is
(a) thin pass-throughs to the real functions and (b) a Streamlit caching
boundary around the network-bound calls.

Caching note: st.cache_data pickles return values, but YieldCurve stores a
closure (its interpolator function) as an instance attribute, which the
standard pickle module cannot serialize. Anything that returns a YieldCurve
(or a dataclass containing one) therefore uses st.cache_resource instead,
which caches the live object by reference rather than pickling it. Plain
dict/DataFrame-returning network calls use st.cache_data.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from corra_pricer.analytics import historical_replay
from corra_pricer.curve_builder.bootstrap import DEFAULT_TENOR_YEARS, bootstrap_zero_curve, reprice_par_bonds
from corra_pricer.curve_builder.curve import YieldCurve
from corra_pricer.market_data.boc_valet_client import fetch_latest_market_snapshot
from corra_pricer.pricing_engine.calendars import (
    BUSINESS_DAY_CONVENTIONS,
    CALENDARS,
)
from corra_pricer.pricing_engine.calendars import add_business_days as _add_business_days
from corra_pricer.pricing_engine.calendars import next_imm_date as _next_imm_date
from corra_pricer.pricing_engine.conventions import DAYCOUNT_CONVENTIONS
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import build_risk_report, compute_extended_risk_metrics, compute_krd
from corra_pricer.risk_engine.risk_report import RiskReport
from corra_pricer.scenario_engine.scenario_engine import (
    ScenarioResult,
    build_scenario_curve,
    run_custom_scenario,
    run_monte_carlo_scenarios,
    run_scenario,
    scenario_summary_table,
)
from corra_pricer.scenario_engine.scenarios import DEFAULT_BUCKETS, SCENARIO_CATALOG

TENORS_YEARS = {"1Y": 1, "2Y": 2, "3Y": 3, "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30}
PAYMENT_FREQUENCIES = {"Annual": 1, "Semiannual": 2, "Quarterly": 4, "Monthly": 12}
DAYCOUNT_CHOICES = list(DAYCOUNT_CONVENTIONS.keys())
BUSINESS_DAY_CONVENTION_CHOICES = list(BUSINESS_DAY_CONVENTIONS.keys())
CALENDAR_CHOICES = list(CALENDARS.keys())
STUB_CHOICES = ["short_first", "long_first", "short_last", "long_last"]
INTERPOLATION_LABELS = {"linear": "Linear", "log_linear_df": "Log-Linear DF", "cubic_spline": "Cubic Spline"}
STUB_LABELS = {
    "short_first": "Short first", "long_first": "Long first",
    "short_last": "Short last", "long_last": "Long last",
}
SCENARIO_CATEGORY_LABELS = {
    "parallel": "Parallel shift", "curve_trade": "Curve trade",
    "macro": "Macro event", "user_defined": "Custom",
}

# The engine keys scenarios by snake_case identifier (inflation_shock, boc_surprise_hike).
# Those are storage keys, not display text -- these helpers turn them into the
# reader-facing labels used in every dropdown, chart axis and table.
_SCENARIO_WORD_FIXES = {"boc": "BoC", "covid": "COVID", "qe": "QE", "qt": "QT"}


def scenario_display_name(key: str) -> str:
    """'inflation_shock' -> 'Inflation shock'; 'parallel_+25bp' -> 'Parallel +25bp'."""
    if key.startswith("parallel_"):
        return f"Parallel {key.split('_', 1)[1]}"
    words = [_SCENARIO_WORD_FIXES.get(w, w) for w in key.split("_")]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def scenario_option_label(key: str) -> str:
    """Dropdown label: prefixes the category so a 41-item list stays scannable,
    except for parallel shifts where the name already says it."""
    name = scenario_display_name(key)
    category = SCENARIO_CATALOG[key].category if key in SCENARIO_CATALOG else ""
    prefix = {"curve_trade": "Curve", "macro": "Macro"}.get(category)
    return f"{prefix} · {name}" if prefix else name


# --- Market data (Module 1) ---------------------------------------------

@st.cache_data(ttl=3600, show_spinner="Pulling live market data from the Bank of Canada...")
def get_market_snapshot() -> dict:
    return fetch_latest_market_snapshot()


@st.cache_resource(ttl=3600, show_spinner="Bootstrapping the discounting curve...")
def get_current_curve(interpolation: str = "linear") -> YieldCurve:
    snapshot = get_market_snapshot()
    return bootstrap_zero_curve(
        snapshot["corra_rate_pct"], snapshot["benchmark_yields_pct"], interpolation=interpolation,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def get_prior_day_snapshot() -> dict:
    """Yesterday's market snapshot, for computing day-over-day deltas.
    Reuses Module 8's fetch_market_snapshot_for_date() -- the same
    nearest-available-date resolution used for historical replay -- so a
    request for "yesterday" on a Monday correctly resolves to Friday's
    close rather than erroring on a weekend gap."""
    yesterday = dt.date.today() - dt.timedelta(days=1)
    return historical_replay.fetch_market_snapshot_for_date(yesterday)


def get_bootstrap_residuals(curve: YieldCurve, benchmark_yields_pct: dict) -> dict:
    return reprice_par_bonds(curve, benchmark_yields_pct)


# --- Pricing (Module 3) ---------------------------------------------------

def build_swap(
    trade_date: dt.date, maturity_date: dt.date, notional: float,
    fixed_rate: float, pay_fixed: bool, payments_per_year: int = 1,
    effective_date: dt.date | None = None,
    fixed_leg_daycount: str = "ACT/365F",
    business_day_convention: str = "None",
    calendar_name: str = "Weekend Only",
    stub: str = "short_first",
) -> CorraOISSwap:
    return CorraOISSwap(
        trade_date=trade_date, effective_date=effective_date or trade_date, maturity_date=maturity_date,
        notional=notional, fixed_rate=fixed_rate, pay_fixed=pay_fixed,
        payments_per_year=payments_per_year, fixed_leg_daycount=fixed_leg_daycount,
        business_day_convention=business_day_convention, calendar_name=calendar_name, stub=stub,
    )


def maturity_from_tenor(trade_date: dt.date, tenor_years: int) -> dt.date:
    return dt.date(trade_date.year + tenor_years, trade_date.month, min(trade_date.day, 28))


def spot_date(trade_date: dt.date, spot_lag_days: int, calendar_name: str = "Canada") -> dt.date:
    """T+n spot lag: steps forward spot_lag_days business days from the
    trade date. Composes calendars.add_business_days(), pre-existing."""
    return _add_business_days(trade_date, spot_lag_days, calendar_name)


def next_imm_date(from_date: dt.date) -> dt.date:
    return _next_imm_date(from_date)


def price_swap(swap: CorraOISSwap, curve: YieldCurve) -> dict:
    return swap.summary(curve)


# --- Risk (Module 4) -------------------------------------------------------

def get_risk_report(swap: CorraOISSwap, curve: YieldCurve) -> RiskReport:
    return build_risk_report(swap, curve)


def get_extended_risk_metrics(swap: CorraOISSwap, curve: YieldCurve) -> dict:
    return compute_extended_risk_metrics(swap, curve)


def get_krd_heatmap_data(curve: YieldCurve, notional: float, fixed_rate: float, pay_fixed: bool,
                          tenors_years: list[int] | None = None) -> dict:
    """KRD for a range of swap tenors, all struck today at the given fixed
    rate/notional -- shows where risk concentrates on the curve for
    different-maturity swaps. Composes build_swap() + compute_krd(), both
    pre-existing; no new pricing logic."""
    tenors_years = tenors_years or [1, 2, 5, 10, 20, 30]
    trade_date = dt.date.today()
    rows = {}
    for years in tenors_years:
        maturity_date = maturity_from_tenor(trade_date, years)
        swap = build_swap(trade_date, maturity_date, notional, fixed_rate, pay_fixed)
        rows[f"{years}Y"] = compute_krd(swap, curve)
    return rows


# --- Scenarios (Module 5) ---------------------------------------------------

def get_scenario_names() -> list[str]:
    return list(SCENARIO_CATALOG.keys())


def get_scenario_catalog() -> dict:
    return SCENARIO_CATALOG


def get_scenario_table(swap: CorraOISSwap, curve: YieldCurve):
    return scenario_summary_table(swap, curve)


def get_scenario_detail(swap: CorraOISSwap, curve: YieldCurve, scenario_name: str) -> ScenarioResult:
    return run_scenario(swap, curve, scenario_name)


def get_scenario_curve(curve: YieldCurve, scenario_name: str):
    return build_scenario_curve(curve, SCENARIO_CATALOG[scenario_name])


def get_custom_scenario_result(swap: CorraOISSwap, curve: YieldCurve, bucket_shocks_bp: dict) -> ScenarioResult:
    return run_custom_scenario(swap, curve, bucket_shocks_bp, name="Custom Shock")


def get_custom_scenario_curve(curve: YieldCurve, bucket_shocks_bp: dict):
    from corra_pricer.scenario_engine.scenarios import Scenario
    return build_scenario_curve(curve, Scenario("custom", "", bucket_shocks_bp, "user_defined"))


def get_monte_carlo_results(swap: CorraOISSwap, curve: YieldCurve, n_simulations: int,
                             shock_std_bp: float, seed: int | None = None):
    return run_monte_carlo_scenarios(swap, curve, n_simulations=n_simulations,
                                      shock_std_bp=shock_std_bp, seed=seed)


# --- Historical replay (Module 8) -------------------------------------------

@st.cache_resource(ttl=3600, show_spinner="Fetching historical curve...")
def get_historical_curve(as_of_date: dt.date, interpolation: str = "linear"):
    return historical_replay.build_historical_curve(as_of_date, interpolation=interpolation)


@st.cache_resource(ttl=3600, show_spinner="Pricing swap on historical date...")
def price_swap_as_of_historical(
    as_of_date: dt.date, tenor_years: int, notional: float,
    fixed_rate: float | None, pay_fixed: bool,
    fixed_leg_daycount: str = "ACT/365F", business_day_convention: str = "None",
    calendar_name: str = "Weekend Only", stub: str = "short_first",
    spot_lag_days: int = 0, use_imm_start: bool = False,
) -> historical_replay.HistoricalPricingResult:
    return historical_replay.price_swap_as_of(
        as_of_date, tenor_years, notional=notional, fixed_rate=fixed_rate, pay_fixed=pay_fixed,
        fixed_leg_daycount=fixed_leg_daycount, business_day_convention=business_day_convention,
        calendar_name=calendar_name, stub=stub, spot_lag_days=spot_lag_days,
        use_imm_start=use_imm_start,
    )


def compare_historical_dates(
    dates: dict, tenor_years: int, notional: float, fixed_rate: float | None, pay_fixed: bool,
    fixed_leg_daycount: str = "ACT/365F", business_day_convention: str = "None",
    calendar_name: str = "Weekend Only", stub: str = "short_first",
    spot_lag_days: int = 0, use_imm_start: bool = False,
):
    return historical_replay.compare_historical_dates(
        dates, tenor_years, notional=notional, fixed_rate=fixed_rate, pay_fixed=pay_fixed,
        fixed_leg_daycount=fixed_leg_daycount, business_day_convention=business_day_convention,
        calendar_name=calendar_name, stub=stub, spot_lag_days=spot_lag_days,
        use_imm_start=use_imm_start,
    )


def get_historical_krd_heatmap(
    dates: dict, tenor_years: int, notional: float, fixed_rate: float | None, pay_fixed: bool,
    fixed_leg_daycount: str = "ACT/365F", business_day_convention: str = "None",
    calendar_name: str = "Weekend Only", stub: str = "short_first",
    spot_lag_days: int = 0, use_imm_start: bool = False,
) -> dict:
    """KRD for the same swap terms, struck fresh on each historical date --
    shows how risk concentration itself shifted as the curve moved through
    the cycle (e.g. a normal curve spreads a 10Y swap's risk across
    buckets; a badly inverted curve can shift it). Composes
    price_swap_as_of_historical() + compute_krd(), both pre-existing."""
    rows = {}
    for label, date in dates.items():
        result = price_swap_as_of_historical(
            date, tenor_years, notional, fixed_rate, pay_fixed,
            fixed_leg_daycount=fixed_leg_daycount, business_day_convention=business_day_convention,
            calendar_name=calendar_name, stub=stub, spot_lag_days=spot_lag_days,
            use_imm_start=use_imm_start,
        )
        rows[label] = compute_krd(result.swap, result.curve)
    return rows


EXAMPLE_HISTORICAL_DATES = historical_replay.EXAMPLE_DATES
