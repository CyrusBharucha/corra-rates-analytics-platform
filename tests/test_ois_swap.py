import datetime as dt

import pytest

from corra_pricer.curve_builder.bootstrap import bootstrap_zero_curve
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap

SAMPLE_YIELDS_PCT = {"2Y": 2.80, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
SAMPLE_CORRA_PCT = 2.29


@pytest.fixture
def curve():
    return bootstrap_zero_curve(SAMPLE_CORRA_PCT, SAMPLE_YIELDS_PCT)


def test_fair_rate_swap_has_zero_npv(curve):
    """Pricing a swap at its own fair rate must produce ~0 NPV -- the fundamental
    sanity check for any swap pricer."""
    trade_date = dt.date(2026, 7, 9)
    swap = CorraOISSwap(
        trade_date=trade_date,
        effective_date=trade_date,
        maturity_date=dt.date(2031, 7, 9),
        notional=10_000_000,
        fixed_rate=0.0,  # placeholder, overwritten below
        pay_fixed=True,
    )
    fair = swap.fair_rate(curve)
    swap.fixed_rate = fair
    assert swap.npv(curve) == pytest.approx(0.0, abs=1.0)  # within $1 on a $10mm notional


def test_pay_fixed_and_receive_fixed_are_mirror_images(curve):
    trade_date = dt.date(2026, 7, 9)
    common_kwargs = dict(
        trade_date=trade_date,
        effective_date=trade_date,
        maturity_date=dt.date(2036, 7, 9),
        notional=5_000_000,
        fixed_rate=0.03,
    )
    payer = CorraOISSwap(**common_kwargs, pay_fixed=True)
    receiver = CorraOISSwap(**common_kwargs, pay_fixed=False)
    assert payer.npv(curve) == pytest.approx(-receiver.npv(curve), abs=1e-6)


def test_higher_fixed_rate_is_worse_for_payer(curve):
    trade_date = dt.date(2026, 7, 9)
    low = CorraOISSwap(trade_date, trade_date, dt.date(2033, 7, 9), 1_000_000, 0.02, pay_fixed=True)
    high = CorraOISSwap(trade_date, trade_date, dt.date(2033, 7, 9), 1_000_000, 0.05, pay_fixed=True)
    assert high.npv(curve) < low.npv(curve)


def test_zero_notional_has_zero_npv(curve):
    trade_date = dt.date(2026, 7, 9)
    swap = CorraOISSwap(trade_date, trade_date, dt.date(2028, 7, 9), 0.0, 0.03, pay_fixed=True)
    assert swap.npv(curve) == pytest.approx(0.0)
