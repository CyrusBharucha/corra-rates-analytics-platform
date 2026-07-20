"""Canadian CORRA OIS market conventions used by the pricing engine.

Day count: ACT/365F is the CORRA OIS market standard and remains the
default and the only day count used for discounting time-to-cashflow
(the curve's own time convention). ACT/360, 30/360, and ACT/ACT are also
available and selectable for the FIXED LEG's accrual calculation
specifically (see DAYCOUNT_CONVENTIONS) -- a genuine, if somewhat unusual,
choice for a CORRA OIS in practice, but exposed here for realism/
completeness since production systems do support day-count selection per
leg. The floating leg's day count is not separately selectable: this
platform's floating leg uses the single-curve telescoping identity
(notional x [DF(start) - DF(end)]), which is a pure discount-factor
relationship with no explicit day-count-dependent compounding calculation
to select a convention for -- see pricing_engine/ois_swap.py.

Business day adjustment and calendars are documented in calendars.py.
Defaults for every new parameter below (day count, business day
convention, calendar, stub) reproduce the platform's original ACT/365F,
unadjusted, short-first-stub behavior exactly -- existing callers are
unaffected unless they opt into the new options.
"""
from __future__ import annotations

import datetime as dt

from corra_pricer.pricing_engine.calendars import adjust

DAYCOUNT_DENOMINATOR = 365.0


def year_fraction(start: dt.date, end: dt.date) -> float:
    """ACT/365 Fixed day count fraction. Used unconditionally for
    discounting time-to-cashflow (the curve's own time convention)."""
    return (end - start).days / DAYCOUNT_DENOMINATOR


def act_360(start: dt.date, end: dt.date) -> float:
    return (end - start).days / 360.0


def thirty_360(start: dt.date, end: dt.date) -> float:
    """30/360 (US/NASD bond-basis)."""
    d1, m1, y1 = start.day, start.month, start.year
    d2, m2, y2 = end.day, end.month, end.year
    if d1 == 31:
        d1 = 30
    if d2 == 31 and d1 == 30:
        d2 = 30
    return ((y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)) / 360.0


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def act_act(start: dt.date, end: dt.date) -> float:
    """ACT/ACT ISDA: splits the period across leap and non-leap portions,
    each divided by its own 365 or 366."""
    if start == end:
        return 0.0
    total = 0.0
    current = start
    while current < end:
        next_year_start = dt.date(current.year + 1, 1, 1)
        period_end = min(next_year_start, end)
        days_in_period = (period_end - current).days
        days_in_year = 366 if _is_leap(current.year) else 365
        total += days_in_period / days_in_year
        current = period_end
    return total


DAYCOUNT_CONVENTIONS = {
    "ACT/365F": year_fraction,
    "ACT/360": act_360,
    "30/360": thirty_360,
    "ACT/ACT": act_act,
}


def _step_back_months(date: dt.date, step_months: int) -> dt.date:
    year, month = date.year, date.month - step_months
    while month <= 0:
        month += 12
        year -= 1
    day = min(date.day, 28)
    return dt.date(year, month, day)


def _step_forward_months(date: dt.date, step_months: int) -> dt.date:
    year, month = date.year, date.month + step_months
    while month > 12:
        month -= 12
        year += 1
    day = min(date.day, 28)
    return dt.date(year, month, day)


def generate_payment_schedule(
    effective_date: dt.date,
    maturity_date: dt.date,
    payments_per_year: int = 1,
    stub: str = "short_first",
    business_day_convention: str = "None",
    calendar_name: str = "Weekend Only",
) -> list[dt.date]:
    """Generates payment dates from effective_date (exclusive) to
    maturity_date (inclusive).

    stub:
      - "short_first" (default): generate backward from maturity in equal
        steps; whatever's left between effective_date and the earliest
        regular anchor becomes its own (typically shorter) first period.
        This reproduces the platform's original behavior exactly.
      - "long_first": same backward generation, but the leftover stub is
        merged into the adjacent period instead of standing alone,
        making the first period longer than a regular period.
      - "short_last" / "long_last": the mirror image, generated forward
        from effective_date, with the stub (if any) at the end instead of
        the start.

    business_day_convention / calendar_name: applied to each generated
    date after the (unadjusted) stub schedule is built. Defaults
    ("None" / "Weekend Only") are no-ops.
    """
    if payments_per_year <= 0:
        raise ValueError("payments_per_year must be positive")
    step_months = 12 // payments_per_year
    if step_months * payments_per_year != 12:
        raise ValueError("payments_per_year must evenly divide 12")
    if stub not in ("short_first", "long_first", "short_last", "long_last"):
        raise ValueError(f"Unknown stub type '{stub}'. Choose from "
                          f"short_first/long_first/short_last/long_last.")

    if stub in ("short_first", "long_first"):
        dates = [maturity_date]
        current = maturity_date
        while True:
            candidate = _step_back_months(current, step_months)
            if candidate <= effective_date:
                break
            dates.append(candidate)
            current = candidate
        dates = sorted(dates)
        if stub == "long_first" and len(dates) > 1:
            dates = dates[1:]  # drop the earliest anchor, merging the stub into the next period
    else:  # short_last / long_last: generate forward from effective_date
        dates = []
        current = effective_date
        while True:
            candidate = _step_forward_months(current, step_months)
            if candidate >= maturity_date:
                break
            dates.append(candidate)
            current = candidate
        if stub == "long_last" and dates:
            dates = dates[:-1]  # drop the latest anchor before maturity, merging the stub forward
        dates.append(maturity_date)
        dates = sorted(dates)

    if business_day_convention != "None" or calendar_name != "Weekend Only":
        dates = sorted({adjust(d, business_day_convention, calendar_name) for d in dates})

    return dates
