"""
Business day calendars and adjustment conventions.

Calendars here are reasonable approximations of the real holiday
calendars (Canadian federal/bank statutory holidays, TARGET), built from
first principles (an Easter/Good-Friday calculation plus "Nth weekday of
month" rules) - not sourced from an official Payments Canada or ECB
calendar feed. Good enough to demonstrate the mechanics of business-day
adjustment correctly; not a substitute for a production holiday calendar
in a real trading system. This limitation is documented deliberately
rather than silently assumed.
"""
from __future__ import annotations

import datetime as dt


def _easter_sunday(year: int) -> dt.date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def _good_friday(year: int) -> dt.date:
    return _easter_sunday(year) - dt.timedelta(days=2)


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> dt.date:
    """weekday: Monday=0 ... Sunday=6. n=1 for 1st occurrence, n=-1 for last."""
    if n > 0:
        d = dt.date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        d += dt.timedelta(days=offset + 7 * (n - 1))
        return d
    # last occurrence: start from next month's 1st, step back
    if month == 12:
        d = dt.date(year + 1, 1, 1)
    else:
        d = dt.date(year, month + 1, 1)
    d -= dt.timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - dt.timedelta(days=offset)


def _observed(date: dt.date) -> dt.date:
    """If date falls on a weekend, the observed holiday moves to the
    following Monday (standard Canadian federal convention)."""
    if date.weekday() == 5:  # Saturday
        return date + dt.timedelta(days=2)
    if date.weekday() == 6:  # Sunday
        return date + dt.timedelta(days=1)
    return date


def _victoria_day(year: int) -> dt.date:
    """Monday on or before May 24 - NOT simply "the last Monday of May":
    when May 25-31 contains a Monday, that Monday falls after May 24 and
    is one week too late."""
    d = dt.date(year, 5, 24)
    return d - dt.timedelta(days=d.weekday())  # weekday(): Monday=0


def canada_holidays(year: int) -> set:
    return {
        _observed(dt.date(year, 1, 1)),          # New Year's Day
        _good_friday(year),                       # Good Friday
        _victoria_day(year),                       # Victoria Day: Monday on/before May 24
        _observed(dt.date(year, 7, 1)),           # Canada Day
        _nth_weekday_of_month(year, 8, 0, 1),      # Civic Holiday: 1st Monday of August
        _nth_weekday_of_month(year, 9, 0, 1),      # Labour Day: 1st Monday of September
        _nth_weekday_of_month(year, 10, 0, 2),     # Thanksgiving: 2nd Monday of October
        _observed(dt.date(year, 11, 11)),         # Remembrance Day
        _observed(dt.date(year, 12, 25)),         # Christmas Day
        _observed(dt.date(year, 12, 26)),         # Boxing Day
    }


def target_holidays(year: int) -> set:
    """Simplified TARGET (Eurozone) calendar: New Year's, Good Friday,
    Easter Monday, Labour Day, Christmas, Boxing Day."""
    easter = _easter_sunday(year)
    return {
        dt.date(year, 1, 1),
        _good_friday(year),
        easter + dt.timedelta(days=1),  # Easter Monday
        dt.date(year, 5, 1),
        dt.date(year, 12, 25),
        dt.date(year, 12, 26),
    }


class Calendar:
    def __init__(self, name: str, holiday_fn=None):
        self.name = name
        self._holiday_fn = holiday_fn
        self._cache: dict[int, set] = {}

    def is_business_day(self, date: dt.date) -> bool:
        if date.weekday() >= 5:  # Saturday/Sunday
            return False
        if self._holiday_fn is None:
            return True
        if date.year not in self._cache:
            self._cache[date.year] = self._holiday_fn(date.year)
        return date not in self._cache[date.year]


CALENDARS = {
    "Canada": Calendar("Canada", canada_holidays),
    "TARGET": Calendar("TARGET", target_holidays),
    "Weekend Only": Calendar("Weekend Only", None),
}


def _shift_days(date: dt.date, days: int) -> dt.date:
    return date + dt.timedelta(days=days)


def following(date: dt.date, calendar: Calendar) -> dt.date:
    while not calendar.is_business_day(date):
        date = _shift_days(date, 1)
    return date


def preceding(date: dt.date, calendar: Calendar) -> dt.date:
    while not calendar.is_business_day(date):
        date = _shift_days(date, -1)
    return date


def modified_following(date: dt.date, calendar: Calendar) -> dt.date:
    adjusted = following(date, calendar)
    if adjusted.month != date.month:
        return preceding(date, calendar)
    return adjusted


def modified_preceding(date: dt.date, calendar: Calendar) -> dt.date:
    adjusted = preceding(date, calendar)
    if adjusted.month != date.month:
        return following(date, calendar)
    return adjusted


def unadjusted(date: dt.date, calendar: Calendar) -> dt.date:
    return date


BUSINESS_DAY_CONVENTIONS = {
    "Following": following,
    "Modified Following": modified_following,
    "Preceding": preceding,
    "Modified Preceding": modified_preceding,
    "None": unadjusted,
}


def adjust(date: dt.date, convention: str, calendar_name: str) -> dt.date:
    if convention not in BUSINESS_DAY_CONVENTIONS:
        raise ValueError(f"Unknown business day convention '{convention}'. "
                          f"Choose from {list(BUSINESS_DAY_CONVENTIONS)}.")
    if calendar_name not in CALENDARS:
        raise ValueError(f"Unknown calendar '{calendar_name}'. Choose from {list(CALENDARS)}.")
    return BUSINESS_DAY_CONVENTIONS[convention](date, CALENDARS[calendar_name])


def add_business_days(date: dt.date, n: int, calendar_name: str = "Canada") -> dt.date:
    """Used for spot lag (T+0/T+1/T+2): steps forward n business days."""
    calendar = CALENDARS[calendar_name]
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    current = date
    while remaining > 0:
        current = _shift_days(current, step)
        if calendar.is_business_day(current):
            remaining -= 1
    return current


def next_imm_date(from_date: dt.date) -> dt.date:
    """Next IMM date on/after from_date: 3rd Wednesday of March, June,
    September, or December."""
    imm_months = [3, 6, 9, 12]
    year = from_date.year
    for _ in range(6):  # at most 5 quarters ahead needed, +1 margin
        for month in imm_months:
            candidate = _nth_weekday_of_month(year, month, 2, 3)  # Wednesday=2, 3rd occurrence
            if candidate >= from_date:
                return candidate
        year += 1
    raise RuntimeError("Could not locate a next IMM date (unexpected).")  # pragma: no cover
