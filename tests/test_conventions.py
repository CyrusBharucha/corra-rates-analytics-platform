import datetime as dt

import pytest

from corra_pricer.pricing_engine.conventions import (
    DAYCOUNT_CONVENTIONS,
    act_360,
    act_act,
    generate_payment_schedule,
    thirty_360,
    year_fraction,
)


# --- Day count conventions ---

def test_full_non_leap_year_all_conventions():
    start, end = dt.date(2026, 1, 1), dt.date(2027, 1, 1)
    assert year_fraction(start, end) == pytest.approx(1.0)
    assert act_360(start, end) == pytest.approx(365 / 360)
    assert thirty_360(start, end) == pytest.approx(1.0)
    assert act_act(start, end) == pytest.approx(1.0)


def test_act_360_always_bigger_than_act_365f_for_same_period():
    start, end = dt.date(2026, 3, 1), dt.date(2026, 9, 1)
    assert act_360(start, end) > year_fraction(start, end)


def test_thirty_360_treats_31st_as_30th():
    start, end = dt.date(2026, 1, 31), dt.date(2026, 3, 31)
    # 30/360: Jan 31 -> 30, Mar 31 -> 30 (since d1 was already clamped to 30)
    assert thirty_360(start, end) == pytest.approx(60 / 360)


def test_act_act_splits_across_leap_year_boundary():
    # 2027 is not a leap year, 2028 is -- period spans Dec 2027 into 2028
    start, end = dt.date(2027, 12, 1), dt.date(2028, 2, 1)
    result = act_act(start, end)
    days_in_2027_portion = (dt.date(2028, 1, 1) - start).days
    days_in_2028_portion = (end - dt.date(2028, 1, 1)).days
    expected = days_in_2027_portion / 365 + days_in_2028_portion / 366
    assert result == pytest.approx(expected)


def test_zero_length_period_is_zero_for_all_conventions():
    d = dt.date(2026, 6, 15)
    for name, fn in DAYCOUNT_CONVENTIONS.items():
        assert fn(d, d) == pytest.approx(0.0), f"{name} nonzero for a zero-length period"


def test_daycount_registry_has_four_conventions():
    assert set(DAYCOUNT_CONVENTIONS.keys()) == {"ACT/365F", "ACT/360", "30/360", "ACT/ACT"}


# --- Schedule generation: backward compatibility ---

def test_default_schedule_matches_original_behavior():
    """Locks in the exact schedule the platform has always produced with no
    stub/BDC/calendar arguments -- a regression guard for the refactor."""
    schedule = generate_payment_schedule(dt.date(2026, 7, 9), dt.date(2031, 7, 9), payments_per_year=1)
    assert schedule == [
        dt.date(2027, 7, 9), dt.date(2028, 7, 9), dt.date(2029, 7, 9),
        dt.date(2030, 7, 9), dt.date(2031, 7, 9),
    ]


def test_default_stub_is_short_first():
    schedule = generate_payment_schedule(dt.date(2026, 3, 1), dt.date(2030, 1, 15), payments_per_year=1)
    first_period_years = (schedule[0] - dt.date(2026, 3, 1)).days / 365.0
    assert first_period_years < 1.0  # shorter than a regular annual period


# --- Stub variants ---

def test_long_first_stub_merges_into_longer_first_period():
    short = generate_payment_schedule(dt.date(2026, 3, 1), dt.date(2030, 1, 15), 1, stub="short_first")
    long = generate_payment_schedule(dt.date(2026, 3, 1), dt.date(2030, 1, 15), 1, stub="long_first")
    assert len(long) == len(short) - 1
    assert long[0] > short[0]  # the first period extends further out


def test_short_last_stub_leaves_a_short_final_period():
    schedule = generate_payment_schedule(dt.date(2026, 3, 1), dt.date(2030, 1, 15), 1, stub="short_last")
    last_period_years = (schedule[-1] - schedule[-2]).days / 365.0
    assert last_period_years < 1.0
    assert schedule[-1] == dt.date(2030, 1, 15)


def test_long_last_stub_merges_into_longer_final_period():
    short = generate_payment_schedule(dt.date(2026, 3, 1), dt.date(2030, 1, 15), 1, stub="short_last")
    long = generate_payment_schedule(dt.date(2026, 3, 1), dt.date(2030, 1, 15), 1, stub="long_last")
    assert len(long) == len(short) - 1
    assert long[-2] < short[-2]  # the period before maturity starts earlier (absorbed the stub)


def test_unknown_stub_raises():
    with pytest.raises(ValueError):
        generate_payment_schedule(dt.date(2026, 1, 1), dt.date(2027, 1, 1), stub="sideways")


# --- Business day adjustment applied to the schedule ---

def test_business_day_convention_no_op_by_default():
    with_default = generate_payment_schedule(dt.date(2026, 7, 9), dt.date(2031, 7, 9), 1)
    with_explicit_none = generate_payment_schedule(
        dt.date(2026, 7, 9), dt.date(2031, 7, 9), 1,
        business_day_convention="None", calendar_name="Weekend Only",
    )
    assert with_default == with_explicit_none


def test_business_day_convention_adjusts_weekend_landing_dates():
    # Jan 1, 2028 is a Saturday -- an annual schedule anchored there should shift
    schedule = generate_payment_schedule(
        dt.date(2027, 1, 1), dt.date(2028, 1, 1), payments_per_year=1,
        business_day_convention="Following", calendar_name="Weekend Only",
    )
    assert schedule[-1] != dt.date(2028, 1, 1)
    assert schedule[-1].weekday() < 5
