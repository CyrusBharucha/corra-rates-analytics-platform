import datetime as dt

import pytest

from corra_pricer.pricing_engine.calendars import (
    CALENDARS,
    add_business_days,
    adjust,
    canada_holidays,
    following,
    modified_following,
    modified_preceding,
    next_imm_date,
    preceding,
    target_holidays,
    unadjusted,
)


# --- Known real-world holiday dates ---

def test_good_friday_2026_is_april_3():
    holidays = canada_holidays(2026)
    assert dt.date(2026, 4, 3) in holidays


def test_victoria_day_never_falls_after_may_24():
    """Victoria Day is defined as the Monday on/before May 24 -- a past bug
    computed 'last Monday of May' instead, which for some years landed on
    May 25-31, after the legal cutoff."""
    for year in range(2020, 2035):
        holidays = canada_holidays(year)
        victoria = [d for d in holidays if d.month == 5]
        assert len(victoria) == 1
        assert victoria[0].day <= 24
        assert victoria[0].weekday() == 0  # Monday


def test_new_years_day_2028_observed_on_monday():
    """Jan 1, 2028 is a Saturday -- the observed holiday should shift to
    the following Monday, Jan 3."""
    holidays = canada_holidays(2028)
    assert dt.date(2028, 1, 3) in holidays
    assert dt.date(2028, 1, 1) not in holidays


def test_canada_holiday_count_is_ten_per_year():
    for year in [2020, 2023, 2026, 2030]:
        assert len(canada_holidays(year)) == 10


def test_target_holidays_smaller_set_than_canada():
    assert len(target_holidays(2026)) < len(canada_holidays(2026))


# --- Business day conventions ---

def test_weekend_only_calendar_has_no_holidays():
    cal = CALENDARS["Weekend Only"]
    assert cal.is_business_day(dt.date(2026, 12, 25))  # Christmas is a normal business day here
    assert not cal.is_business_day(dt.date(2026, 7, 4))  # a Saturday


def test_following_skips_weekend_forward():
    saturday = dt.date(2026, 7, 4)
    result = adjust(saturday, "Following", "Weekend Only")
    assert result == dt.date(2026, 7, 6)
    assert result.weekday() == 0


def test_preceding_skips_weekend_backward():
    saturday = dt.date(2026, 7, 4)
    result = adjust(saturday, "Preceding", "Weekend Only")
    assert result == dt.date(2026, 7, 3)


def test_following_can_roll_into_next_month():
    # Jan 31, 2026 is a Saturday
    result = adjust(dt.date(2026, 1, 31), "Following", "Weekend Only")
    assert result.month == 2


def test_modified_following_rolls_back_instead_of_forward_at_month_end():
    result = adjust(dt.date(2026, 1, 31), "Modified Following", "Weekend Only")
    assert result.month == 1
    assert result == dt.date(2026, 1, 30)


def test_modified_preceding_rolls_forward_instead_of_back_at_month_start():
    # Aug 1, 2026 is a Saturday -- Preceding would roll back into July
    result = adjust(dt.date(2026, 8, 1), "Modified Preceding", "Weekend Only")
    assert result.month == 8


def test_none_convention_is_a_no_op():
    saturday = dt.date(2026, 7, 4)
    assert adjust(saturday, "None", "Canada") == saturday


def test_business_day_stays_unchanged_under_all_conventions():
    tuesday = dt.date(2026, 7, 7)
    for convention in ["Following", "Preceding", "Modified Following", "Modified Preceding", "None"]:
        assert adjust(tuesday, convention, "Weekend Only") == tuesday


def test_unknown_convention_raises():
    with pytest.raises(ValueError):
        adjust(dt.date(2026, 1, 1), "Nonsense", "Canada")


def test_unknown_calendar_raises():
    with pytest.raises(ValueError):
        adjust(dt.date(2026, 1, 1), "Following", "Nonsense")


# --- Spot lag ---

def test_add_business_days_skips_weekend():
    thursday = dt.date(2026, 7, 9)
    assert add_business_days(thursday, 2, "Weekend Only") == dt.date(2026, 7, 13)  # skips Sat/Sun


def test_add_business_days_zero_is_identity():
    d = dt.date(2026, 7, 9)
    assert add_business_days(d, 0, "Weekend Only") == d


# --- IMM dates ---

def test_next_imm_date_is_third_wednesday():
    result = next_imm_date(dt.date(2026, 7, 9))
    assert result.weekday() == 2  # Wednesday
    assert result.month in (3, 6, 9, 12)
    assert 15 <= result.day <= 21  # 3rd Wednesday always falls in this range


def test_next_imm_date_on_an_imm_date_returns_itself():
    imm = next_imm_date(dt.date(2026, 7, 9))
    assert next_imm_date(imm) == imm


def test_next_imm_date_is_never_before_requested_date():
    for month_offset in range(0, 24):
        year = 2026 + month_offset // 12
        month = month_offset % 12 + 1
        d = dt.date(year, month, 10)
        assert next_imm_date(d) >= d
