"""
Historical replay (Module 8): price a swap on any historical date where BoC
Valet market data exists, and compare how the curve and a swap's risk
profile actually looked across real historical episodes - e.g. "here's
what a 5Y CORRA OIS looked like in March 2020 vs. March 2022 vs. October
2023 vs. today."

This module deliberately contains NO new pricing or risk math. It is a thin
orchestration layer that reuses, unmodified:
  - Module 1 (market_data.boc_valet_client) for the historical data pull,
  - Module 2 (curve_builder.bootstrap) to reconstruct that date's curve,
  - Module 3 (pricing_engine.ois_swap) to build and price the swap,
  - Module 4 (risk_engine.risk_engine) for the full risk report (DV01, PV01,
    KRD, convexity).
The only new logic here is: (a) resolving a requested calendar date to the
nearest actual data date, and (b) looping that pipeline over multiple dates
and tabulating the results for comparison.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from corra_pricer.curve_builder.bootstrap import DEFAULT_TENOR_YEARS, bootstrap_zero_curve
from corra_pricer.curve_builder.curve import YieldCurve
from corra_pricer.market_data.boc_valet_client import (
    BocValetError,
    fetch_benchmark_yields,
    fetch_corra_history,
    fetch_latest_market_snapshot,
)
from corra_pricer.pricing_engine.calendars import add_business_days, next_imm_date
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_engine import build_risk_report
from corra_pricer.risk_engine.risk_report import RiskReport

# Real, well-known episodes in Canadian rates markets - actual calendar
# dates, not synthetic scenarios. Confirmed available in the BoC Valet
# API's history (CORRA and benchmark yield series both extend back well
# before 2020). Kept as a full timeline (not just 3-4 checkpoints) so the
# Historical Replay page can animate a real multi-year progression rather
# than a handful of snapshots.
EXAMPLE_DATES = {
    # Listed in chronological order - the Historical Replay page's timeline/
    # animation plays through dict insertion order, so this ordering matters.
    "march_2020": dt.date(2020, 3, 23),         # depths of the COVID crash / emergency cuts
    "qe_2020": dt.date(2020, 6, 1),             # BoC's Government Bond Purchase Program in full swing
    "recovery_2021": dt.date(2021, 9, 1),       # post-COVID recovery, rates still pinned near zero
    "march_2022": dt.date(2022, 3, 2),          # eve of the BoC's first 2022 hike
    "inflation_peak_2022": dt.date(2022, 7, 13),  # BoC's surprise 100bp hike, inflation fight intensifying
    "hiking_peak_2023": dt.date(2023, 7, 12),   # BoC reaches its 5.00% terminal rate for the cycle
    "october_2023": dt.date(2023, 10, 2),       # "higher for longer" term-premium repricing, after the last hike
    "first_cut_2024": dt.date(2024, 6, 5),      # BoC's first cut of the easing cycle
    "mid_2025": dt.date(2025, 1, 15),           # a year into the easing cycle
}

LOOKBACK_DAYS_FOR_NEAREST_DATE = 10


def _lookup_window(requested_date: dt.date, days_back: int = LOOKBACK_DAYS_FOR_NEAREST_DATE):
    return requested_date - dt.timedelta(days=days_back), requested_date


def fetch_market_snapshot_for_date(as_of_date: dt.date) -> dict:
    """Resolves as_of_date to the most recent actual publication date on or
    before it (weekends/holidays aren't published, so an exact-date request
    commonly needs to fall back a day or two), and returns that date's
    CORRA fixing and GoC benchmark yields.

    Raises BocValetError if no data is available at all in the lookback
    window (e.g. as_of_date predates the Valet API's history).
    """
    start, end = _lookup_window(as_of_date)
    corra = fetch_corra_history(start_date=start, end_date=end)
    yields = fetch_benchmark_yields(start_date=start, end_date=end)
    if corra.empty or yields.empty:
        raise BocValetError(
            f"No CORRA/benchmark-yield data found in the {LOOKBACK_DAYS_FOR_NEAREST_DATE} days "
            f"up to {as_of_date}. This date may predate available history."
        )
    corra_row = corra.iloc[-1]
    yields_row = yields.iloc[-1]
    return {
        "requested_date": as_of_date,
        "corra_data_date": corra_row["date"].date(),
        "yields_data_date": yields_row["date"].date(),
        "corra_pct": float(corra_row["corra"]),
        "yields_pct": {tenor: float(yields_row[tenor]) for tenor in DEFAULT_TENOR_YEARS},
    }


def build_historical_curve(as_of_date: dt.date, interpolation: str = "linear") -> tuple[YieldCurve, dict]:
    """Fetches that date's market snapshot and bootstraps a curve from it
    (Module 2's bootstrap_zero_curve, unmodified)."""
    snapshot = fetch_market_snapshot_for_date(as_of_date)
    curve = bootstrap_zero_curve(
        snapshot["corra_pct"], snapshot["yields_pct"], interpolation=interpolation,
        label=f"GoC-Proxy OIS Zero Curve as of {snapshot['yields_data_date']}",
    )
    return curve, snapshot


@dataclass
class HistoricalPricingResult:
    requested_date: dt.date
    data_date: dt.date
    curve: YieldCurve
    swap: CorraOISSwap
    npv: float
    fair_rate_pct: float
    risk: RiskReport

    def to_dict(self) -> dict:
        row = {
            "requested_date": self.requested_date,
            "data_date": self.data_date,
            "fair_rate_pct": self.fair_rate_pct,
            "fixed_rate_pct": self.swap.fixed_rate * 100,
            "npv": self.npv,
            "dv01": self.risk.dv01,
            "pv01": self.risk.pv01,
            "convexity": self.risk.convexity,
        }
        for bucket, val in self.risk.krd.items():
            row[f"krd_{bucket}"] = val
        for tenor in DEFAULT_TENOR_YEARS:
            row[f"curve_{tenor}_pct"] = self.curve.zero_rate(DEFAULT_TENOR_YEARS[tenor]) * 100
        return row


def price_swap_as_of(
    as_of_date: dt.date,
    tenor_years: int,
    notional: float = 10_000_000,
    fixed_rate: float | None = None,
    pay_fixed: bool = True,
    payments_per_year: int = 1,
    interpolation: str = "linear",
    fixed_leg_daycount: str = "ACT/365F",
    business_day_convention: str = "None",
    calendar_name: str = "Weekend Only",
    stub: str = "short_first",
    spot_lag_days: int = 0,
    effective_date_override: dt.date | None = None,
    use_imm_start: bool = False,
) -> HistoricalPricingResult:
    """Prices a fresh tenor_years CORRA OIS struck on as_of_date, using that
    date's actual historical market data. If fixed_rate is omitted, the
    swap is priced at that date's fair (par) rate. Returns NPV, fair rate,
    and a full Module-4 risk report - all computed by the existing pricer
    and risk engine, unchanged.

    Convention parameters (fixed_leg_daycount, business_day_convention,
    calendar_name, stub) and start-date parameters (spot_lag_days,
    effective_date_override, use_imm_start) give this function the same
    swap-configuration surface as the Pricing page's build_swap() - every
    default reproduces the platform's original as_of_date-is-also-
    effective-date behavior exactly, so existing callers are unaffected.

    as_of_date always remains the market-data reference date (the date
    whose curve is used) - effective_date_override/spot_lag_days/
    use_imm_start only move the swap's *own* start date, mirroring how the
    Pricing page lets trade date and effective date diverge (spot lag,
    forward start, IMM start) without changing which market snapshot
    prices the swap. use_imm_start is resolved per as_of_date (each
    historical date gets its own next-IMM-date) rather than a single fixed
    override, since a shared absolute IMM date wouldn't be meaningful
    across multiple different historical checkpoints.
    """
    curve, snapshot = build_historical_curve(as_of_date, interpolation=interpolation)

    spot = add_business_days(as_of_date, spot_lag_days, "Canada") if spot_lag_days else as_of_date
    if use_imm_start:
        effective_date = next_imm_date(spot)
    elif effective_date_override is not None:
        effective_date = effective_date_override
    else:
        effective_date = spot

    maturity_date = dt.date(effective_date.year + tenor_years, effective_date.month, min(effective_date.day, 28))

    swap = CorraOISSwap(
        trade_date=as_of_date, effective_date=effective_date, maturity_date=maturity_date,
        notional=notional, fixed_rate=0.0, pay_fixed=pay_fixed, payments_per_year=payments_per_year,
        fixed_leg_daycount=fixed_leg_daycount, business_day_convention=business_day_convention,
        calendar_name=calendar_name, stub=stub,
    )
    fair_rate = swap.fair_rate(curve)
    swap.fixed_rate = fair_rate if fixed_rate is None else fixed_rate

    return HistoricalPricingResult(
        requested_date=as_of_date,
        data_date=snapshot["yields_data_date"],
        curve=curve,
        swap=swap,
        npv=swap.npv(curve),
        fair_rate_pct=fair_rate * 100,
        risk=build_risk_report(swap, curve),
    )


def compare_historical_dates(
    dates: dict | list,
    tenor_years: int,
    notional: float = 10_000_000,
    fixed_rate: float | None = None,
    pay_fixed: bool = True,
    interpolation: str = "linear",
    fixed_leg_daycount: str = "ACT/365F",
    business_day_convention: str = "None",
    calendar_name: str = "Weekend Only",
    stub: str = "short_first",
    spot_lag_days: int = 0,
    use_imm_start: bool = False,
) -> pd.DataFrame:
    """Runs price_swap_as_of() across multiple dates and returns one
    comparison table. `dates` can be a list of dt.date, or a
    {label: dt.date} dict (labels become the 'label' column). Every swap-
    configuration parameter (day count, stub, business day convention,
    calendar, spot lag, IMM start) is applied identically across all dates
    - the same swap configuration, compared through time, same as picking
    one configuration on the Pricing page and asking "how would this exact
    swap have looked on each of these historical dates.\""""
    if isinstance(dates, dict):
        labeled_dates = list(dates.items())
    else:
        labeled_dates = [(d.isoformat(), d) for d in dates]

    rows = []
    for label, date in labeled_dates:
        result = price_swap_as_of(
            date, tenor_years, notional=notional, fixed_rate=fixed_rate,
            pay_fixed=pay_fixed, interpolation=interpolation,
            fixed_leg_daycount=fixed_leg_daycount, business_day_convention=business_day_convention,
            calendar_name=calendar_name, stub=stub, spot_lag_days=spot_lag_days,
            use_imm_start=use_imm_start,
        )
        row = {"label": label, **result.to_dict()}
        rows.append(row)
    return pd.DataFrame(rows)


def compare_example_dates(tenor_years: int = 5, notional: float = 10_000_000,
                           fixed_rate: float | None = None, pay_fixed: bool = True,
                           include_today: bool = True) -> pd.DataFrame:
    """Convenience wrapper around EXAMPLE_DATES (+ 'today', the latest
    available data date) - the exact "March 2020 vs March 2022 vs October
    2023 vs today" comparison this module exists to produce."""
    dates = dict(EXAMPLE_DATES)
    if include_today:
        latest = fetch_latest_market_snapshot()
        dates["today"] = latest["as_of_yields"].date()
    return compare_historical_dates(dates, tenor_years, notional=notional,
                                     fixed_rate=fixed_rate, pay_fixed=pay_fixed)
