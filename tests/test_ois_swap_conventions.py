import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap

NORMAL_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
NORMAL_CORRA_PCT = 2.29
TRADE_DATE = dt.date(2026, 7, 9)
MATURITY_5Y = dt.date(2031, 7, 9)


@pytest.fixture
def curve():
    return bootstrap_zero_curve(NORMAL_CORRA_PCT, NORMAL_YIELDS_PCT)


# --- Backward compatibility ---

def test_default_swap_construction_unaffected_by_new_fields(curve):
    """A swap built with no convention kwargs must behave identically to
    before these fields existed."""
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True)
    assert swap.fixed_leg_daycount == "ACT/365F"
    assert swap.business_day_convention == "None"
    assert swap.calendar_name == "Weekend Only"
    assert swap.stub == "short_first"
    fair = swap.fair_rate(curve)
    swap.fixed_rate = fair
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)


# --- Fixed leg day count selection ---

@pytest.mark.parametrize("daycount", ["ACT/365F", "ACT/360", "30/360", "ACT/ACT"])
def test_swap_reprices_to_par_at_its_own_fair_rate_under_every_daycount(curve, daycount):
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.0, pay_fixed=True,
                         fixed_leg_daycount=daycount)
    swap.fixed_rate = swap.fair_rate(curve)
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)


def test_act_360_fair_rate_lower_than_act_365f(curve):
    """ACT/360 gives a larger accrual fraction for the same calendar period
    than ACT/365F, so a smaller coupon rate is needed to match the same PV."""
    act365 = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.0, pay_fixed=True,
                           fixed_leg_daycount="ACT/365F")
    act360 = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.0, pay_fixed=True,
                           fixed_leg_daycount="ACT/360")
    assert act360.fair_rate(curve) < act365.fair_rate(curve)


def test_daycount_does_not_affect_discounting_time(curve):
    """_t() (discounting time-to-cashflow) is always ACT/365F regardless of
    fixed_leg_daycount -- only the accrual/coupon-size calculation changes."""
    act365 = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True,
                           fixed_leg_daycount="ACT/365F")
    act360 = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True,
                           fixed_leg_daycount="ACT/360")
    for cf365, cf360 in zip(act365.fixed_leg_cashflows(), act360.fixed_leg_cashflows()):
        assert act365._t(cf365["end"]) == act360._t(cf360["end"])


# --- Stub handling ---

def test_long_first_stub_reprices_to_par(curve):
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 9, 15), 10_000_000, 0.0,
                         pay_fixed=True, stub="long_first")
    swap.fixed_rate = swap.fair_rate(curve)
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)


def test_short_last_stub_reprices_to_par(curve):
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 9, 15), 10_000_000, 0.0,
                         pay_fixed=True, stub="short_last")
    swap.fixed_rate = swap.fair_rate(curve)
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)


def test_stub_choice_changes_payment_dates(curve):
    short_first = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 9, 15), 10_000_000, 0.03,
                                pay_fixed=True, stub="short_first")
    long_first = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 9, 15), 10_000_000, 0.03,
                               pay_fixed=True, stub="long_first")
    assert short_first.payment_dates != long_first.payment_dates
    assert len(long_first.payment_dates) == len(short_first.payment_dates) - 1


# --- Business day convention / calendar ---

def test_business_day_convention_reprices_to_par(curve):
    swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.0, pay_fixed=True,
                         business_day_convention="Modified Following", calendar_name="Canada")
    swap.fixed_rate = swap.fair_rate(curve)
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)


def test_business_day_convention_can_shift_payment_dates(curve):
    unadjusted_swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True)
    adjusted_swap = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True,
                                  business_day_convention="Modified Following", calendar_name="Canada")
    assert unadjusted_swap.payment_dates != adjusted_swap.payment_dates
    for d in adjusted_swap.payment_dates:
        assert d.weekday() < 5  # every adjusted date lands on a business day


# --- Payer/receiver mirror still holds under non-default conventions ---

def test_payer_receiver_mirror_holds_under_act_360(curve):
    payer = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=True,
                          fixed_leg_daycount="ACT/360")
    receiver = CorraOISSwap(TRADE_DATE, TRADE_DATE, MATURITY_5Y, 10_000_000, 0.03, pay_fixed=False,
                             fixed_leg_daycount="ACT/360")
    assert payer.npv(curve) == pytest.approx(-receiver.npv(curve), abs=1e-6)


def test_payer_receiver_mirror_holds_under_bdc_and_stub(curve):
    kwargs = dict(business_day_convention="Modified Following", calendar_name="Canada", stub="long_first")
    payer = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 9, 15), 10_000_000, 0.03,
                          pay_fixed=True, **kwargs)
    receiver = CorraOISSwap(TRADE_DATE, TRADE_DATE, dt.date(2031, 9, 15), 10_000_000, 0.03,
                             pay_fixed=False, **kwargs)
    assert payer.npv(curve) == pytest.approx(-receiver.npv(curve), abs=1e-6)
