"""
Scenario catalog: named, documented curve shocks a rates desk asks about
constantly. Every scenario is expressed as a set of key-rate bucket shocks
(in bp) at the same 2Y/5Y/10Y/30Y buckets the risk engine uses -- so a
"parallel +25bp" scenario is just an equal shock at all four buckets, which,
thanks to the tent-weight partition-of-unity property (see
curve_builder/shocked_curve.py), reconstructs an exact true parallel shift.
Curve trades and macro scenarios use unequal bucket shocks to twist or tilt
the curve shape.

Macro scenario shapes are illustrative, stylized assumptions for
demonstration -- not calibrated forecasts -- grounded in standard rates
intuition:
  - A central bank surprise is a shock to the near-term expected policy
    path; it fades toward the long end because long yields price in a
    reversion to a neutral rate, not a permanent level shift. This is why
    "surprise hike/cut" scenarios are front-loaded and decay by maturity
    (a bear/bull FLATTENER shape).
  - An inflation shock raises the compensation investors demand for holding
    long-dated fixed cashflows (the inflation/term premium) much more than
    it raises near-term rates, which are anchored by current policy (a bear
    STEEPENER shape).
  - A recession scenario prices in an aggressive future cutting cycle: the
    front end falls hardest as cuts get priced in, while the long end falls
    less (or barely) since it already reflects a lower long-run neutral
    rate (a bull STEEPENER shape).
  - QT (quantitative tightening) raises the long end disproportionately as
    central bank balance-sheet runoff increases net bond supply the market
    must absorb (a term-premium / bear-steepener effect); QE does the
    opposite (bull flattener, the long end pinned down by central bank
    purchases).

Distinct from Module 8 (historical replay), which prices swaps on REAL
historical dates using REAL Bank of Canada data -- these macro scenarios
are named after real episodes for intuition, but the shock magnitudes
below are illustrative/stylized, not a reproduction of what actually
happened on any specific date. Use Module 8 if you want the real thing.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BUCKETS = [2.0, 5.0, 10.0, 30.0]


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    bucket_shocks_bp: dict  # {bucket_time_years: shock_in_bp}
    category: str


def _parallel(bp: float) -> dict:
    return {b: bp for b in DEFAULT_BUCKETS}


def _two_point(short_bp: float, long_bp: float, short: float = 2.0, long: float = 10.0) -> dict:
    return {short: short_bp, long: long_bp}


def _four_point(y2: float, y5: float, y10: float, y30: float) -> dict:
    return {2.0: y2, 5.0: y5, 10.0: y10, 30.0: y30}


PARALLEL_MAGNITUDES_BP = [1, 5, 10, 25, 50, 100, 200]
PARALLEL_SCENARIOS = {}
for _bp in PARALLEL_MAGNITUDES_BP:
    for _sign, _label in [(1, "+"), (-1, "-")]:
        _name = f"parallel_{_label}{_bp}bp"
        PARALLEL_SCENARIOS[_name] = Scenario(
            _name, f"Parallel curve shift, {_label}{_bp}bp", _parallel(_sign * _bp), "parallel",
        )

CURVE_TRADE_SCENARIOS = {
    "2s10s_steepener": Scenario(
        "2s10s_steepener", "2Y -12.5bp / 10Y +12.5bp: 2s10s spread widens (steepens)",
        _two_point(-12.5, 12.5, 2.0, 10.0), "curve_trade",
    ),
    "2s10s_flattener": Scenario(
        "2s10s_flattener", "2Y +12.5bp / 10Y -12.5bp: 2s10s spread narrows (flattens)",
        _two_point(12.5, -12.5, 2.0, 10.0), "curve_trade",
    ),
    "5s30s_steepener": Scenario(
        "5s30s_steepener", "5Y -12.5bp / 30Y +12.5bp: 5s30s spread widens (steepens)",
        _two_point(-12.5, 12.5, 5.0, 30.0), "curve_trade",
    ),
    "5s30s_flattener": Scenario(
        "5s30s_flattener", "5Y +12.5bp / 30Y -12.5bp: 5s30s spread narrows (flattens)",
        _two_point(12.5, -12.5, 5.0, 30.0), "curve_trade",
    ),
    "bear_steepener": Scenario(
        "bear_steepener",
        "Rates rise overall, long end rises more (curve steepens while selling off) "
        "-- 2Y +10 / 5Y +18 / 10Y +25 / 30Y +30bp",
        _four_point(10, 18, 25, 30), "curve_trade",
    ),
    "bull_steepener": Scenario(
        "bull_steepener",
        "Rates fall overall, short end falls more (curve steepens while rallying) "
        "-- 2Y -30 / 5Y -20 / 10Y -12 / 30Y -5bp",
        _four_point(-30, -20, -12, -5), "curve_trade",
    ),
    "bear_flattener": Scenario(
        "bear_flattener",
        "Rates rise overall, short end rises more (curve flattens while selling off) "
        "-- 2Y +30 / 5Y +20 / 10Y +12 / 30Y +5bp",
        _four_point(30, 20, 12, 5), "curve_trade",
    ),
    "bull_flattener": Scenario(
        "bull_flattener",
        "Rates fall overall, long end falls more (curve flattens while rallying) "
        "-- 2Y -10 / 5Y -18 / 10Y -25 / 30Y -30bp",
        _four_point(-10, -18, -25, -30), "curve_trade",
    ),
    "twist": Scenario(
        "twist",
        "Rotation around the belly: short end down, long end up, 5Y roughly "
        "anchored -- 2Y -15 / 5Y 0 / 10Y +15 / 30Y +20bp",
        _four_point(-15, 0, 15, 20), "curve_trade",
    ),
    "butterfly": Scenario(
        "butterfly",
        "Wings up, belly down (belly outperforms) -- 2Y +10 / 5Y -15 / 10Y -15 / 30Y +10bp",
        _four_point(10, -15, -15, 10), "curve_trade",
    ),
    "humped": Scenario(
        "humped",
        "Belly up, wings down (belly underperforms) -- 2Y -5 / 5Y +15 / 10Y +15 / 30Y -5bp",
        _four_point(-5, 15, 15, -5), "curve_trade",
    ),
    "inverted": Scenario(
        "inverted",
        "Sustained inversion: front end sharply higher than the long end -- "
        "2Y +50 / 5Y +20 / 10Y -10 / 30Y -30bp",
        _four_point(50, 20, -10, -30), "curve_trade",
    ),
}

MACRO_SCENARIOS = {
    "boc_surprise_hike": Scenario(
        "boc_surprise_hike",
        "BoC hikes more than priced in: front-loaded rise, decaying by maturity "
        "(bear flattener shape) -- 2Y +25 / 5Y +15 / 10Y +8 / 30Y +3bp",
        _four_point(25, 15, 8, 3), "macro",
    ),
    "boc_surprise_cut": Scenario(
        "boc_surprise_cut",
        "BoC cuts more than priced in: front-loaded fall, decaying by maturity "
        "(bull steepener shape) -- 2Y -25 / 5Y -15 / 10Y -8 / 30Y -3bp",
        _four_point(-25, -15, -8, -3), "macro",
    ),
    "inflation_shock": Scenario(
        "inflation_shock",
        "Inflation surprise repriced into the term/inflation premium, hitting the "
        "long end hardest (bear steepener shape) -- 2Y +5 / 5Y +15 / 10Y +30 / 30Y +40bp",
        _four_point(5, 15, 30, 40), "macro",
    ),
    "recession": Scenario(
        "recession",
        "Recession: an aggressive future cutting cycle gets priced in fast at the "
        "front end (bull steepener shape) -- 2Y -75 / 5Y -50 / 10Y -25 / 30Y -10bp",
        _four_point(-75, -50, -25, -10), "macro",
    ),
    "covid_panic": Scenario(
        "covid_panic",
        "Acute flight-to-quality panic: front end collapses on emergency-cut bets "
        "-- 2Y -40 / 5Y -30 / 10Y -15 / 30Y -5bp",
        _four_point(-40, -30, -15, -5), "macro",
    ),
    "covid_easing": Scenario(
        "covid_easing",
        "Sustained emergency easing plus QE-style long-end suppression -- broad, "
        "roughly parallel cuts -- 2Y -20 / 5Y -15 / 10Y -20 / 30Y -25bp",
        _four_point(-20, -15, -20, -25), "macro",
    ),
    "hiking_cycle_begins": Scenario(
        "hiking_cycle_begins",
        "Front-loaded shock as the market prices the start of a hiking cycle plus "
        "several more hikes to come -- 2Y +40 / 5Y +25 / 10Y +15 / 30Y +5bp",
        _four_point(40, 25, 15, 5), "macro",
    ),
    "hiking_cycle_peak": Scenario(
        "hiking_cycle_peak",
        "'Higher for longer' repricing near a hiking cycle's peak: inversion "
        "deepens as recession risk builds at the long end -- 2Y +15 / 5Y 0 / "
        "10Y -10 / 30Y -15bp",
        _four_point(15, 0, -10, -15), "macro",
    ),
    "banking_crisis": Scenario(
        "banking_crisis",
        "Sharp flight-to-quality on banking-sector stress: front end collapses on "
        "fast rate-cut bets -- 2Y -60 / 5Y -35 / 10Y -15 / 30Y -5bp",
        _four_point(-60, -35, -15, -5), "macro",
    ),
    "quantitative_tightening": Scenario(
        "quantitative_tightening",
        "QT: balance-sheet runoff increases net bond supply, pushing the long end "
        "up disproportionately (term-premium bear steepener) -- 2Y +5 / 5Y +10 / "
        "10Y +20 / 30Y +30bp",
        _four_point(5, 10, 20, 30), "macro",
    ),
    "quantitative_easing": Scenario(
        "quantitative_easing",
        "QE: central bank purchases pin the long end down disproportionately "
        "(bull flattener) -- 2Y -2 / 5Y -8 / 10Y -20 / 30Y -30bp",
        _four_point(-2, -8, -20, -30), "macro",
    ),
    "emergency_cut": Scenario(
        "emergency_cut",
        "A single large surprise emergency cut, sharply front-loaded -- "
        "2Y -50 / 5Y -30 / 10Y -15 / 30Y -5bp",
        _four_point(-50, -30, -15, -5), "macro",
    ),
    "soft_landing": Scenario(
        "soft_landing",
        "Gradual, benign normalization: mild cuts priced in gently, long end "
        "roughly flat -- 2Y -10 / 5Y -5 / 10Y 0 / 30Y +2bp",
        _four_point(-10, -5, 0, 2), "macro",
    ),
    "sticky_inflation": Scenario(
        "sticky_inflation",
        "Inflation proves more persistent than expected: broadly higher yields "
        "with a front-end tilt as 'higher for longer' gets priced in -- "
        "2Y +20 / 5Y +25 / 10Y +20 / 30Y +15bp",
        _four_point(20, 25, 20, 15), "macro",
    ),
    "stagflation": Scenario(
        "stagflation",
        "Worst-case: inflation/term premium dominates and drives a severe bear "
        "steepener even as growth concerns build -- 2Y +15 / 5Y +25 / 10Y +45 / "
        "30Y +60bp",
        _four_point(15, 25, 45, 60), "macro",
    ),
}

SCENARIO_CATALOG = {**PARALLEL_SCENARIOS, **CURVE_TRADE_SCENARIOS, **MACRO_SCENARIOS}
