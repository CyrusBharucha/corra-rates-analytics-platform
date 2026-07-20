import datetime as dt
from unittest.mock import patch

import pandas as pd
import pytest

from corra_pricer.analytics import historical_replay as hr


def _corra_frame(rows):
    return pd.DataFrame({"date": [pd.Timestamp(d) for d, _ in rows], "corra": [v for _, v in rows]})


def _yields_frame(rows):
    data = {"date": [pd.Timestamp(d) for d, _ in rows]}
    tenors = ["2Y", "3Y", "5Y", "7Y", "10Y", "LONG"]
    for i, t in enumerate(tenors):
        data[t] = [vals[i] for _, vals in rows]
    return pd.DataFrame(data)


FIXED_DATE = dt.date(2022, 3, 2)  # a Wednesday
CORRA_ROWS = [("2022-03-02", 0.17)]
YIELDS_ROWS = [("2022-03-02", [1.47, 1.65, 1.75, 1.79, 1.81, 2.09])]


def _patched():
    return patch.object(hr, "fetch_corra_history", return_value=_corra_frame(CORRA_ROWS)), \
        patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(YIELDS_ROWS))


# --- Backward compatibility ---

def test_default_effective_date_still_equals_as_of_date():
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(FIXED_DATE, tenor_years=5)
    assert result.swap.effective_date == FIXED_DATE
    assert result.swap.trade_date == FIXED_DATE
    assert result.swap.fixed_leg_daycount == "ACT/365F"
    assert result.swap.business_day_convention == "None"
    assert result.swap.stub == "short_first"


# --- Spot lag ---

def test_spot_lag_shifts_effective_date_forward():
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, spot_lag_days=2)
    assert result.swap.trade_date == FIXED_DATE  # trade/market-data date unchanged
    assert result.swap.effective_date > FIXED_DATE
    assert result.swap.effective_date == dt.date(2022, 3, 4)  # T+2 business days from a Wednesday


def test_zero_spot_lag_is_identity():
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, spot_lag_days=0)
    assert result.swap.effective_date == FIXED_DATE


# --- IMM start ---

def test_imm_start_lands_on_third_wednesday():
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, use_imm_start=True)
    assert result.swap.effective_date.weekday() == 2  # Wednesday
    assert result.swap.effective_date >= FIXED_DATE
    assert result.swap.effective_date.month in (3, 6, 9, 12)


def test_imm_start_combines_with_spot_lag():
    """IMM date should be resolved from the spot-lagged date, not raw as_of_date."""
    p1, p2 = _patched()
    with p1, p2:
        no_lag = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, use_imm_start=True)
        with_lag = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, use_imm_start=True, spot_lag_days=2)
    # both resolve to the same or a later IMM date once lagged forward
    assert with_lag.swap.effective_date >= no_lag.swap.effective_date


def test_explicit_effective_date_override_takes_precedence():
    override = dt.date(2022, 6, 1)
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, effective_date_override=override)
    assert result.swap.effective_date == override
    assert result.swap.trade_date == FIXED_DATE


# --- Convention parameters reprice to par ---

@pytest.mark.parametrize("daycount", ["ACT/365F", "ACT/360", "30/360", "ACT/ACT"])
def test_reprices_to_par_under_every_daycount(daycount):
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, fixed_leg_daycount=daycount)
    assert result.npv == pytest.approx(0.0, abs=1.0)


def test_reprices_to_par_with_bdc_and_stub():
    p1, p2 = _patched()
    with p1, p2:
        result = hr.price_swap_as_of(
            FIXED_DATE, tenor_years=5, business_day_convention="Modified Following",
            calendar_name="Canada", stub="long_first",
        )
    assert result.npv == pytest.approx(0.0, abs=1.0)


def test_act_360_gives_different_fair_rate_than_act_365f():
    p1, p2 = _patched()
    with p1, p2:
        act365 = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, fixed_leg_daycount="ACT/365F")
        act360 = hr.price_swap_as_of(FIXED_DATE, tenor_years=5, fixed_leg_daycount="ACT/360")
    assert act360.fair_rate_pct != act365.fair_rate_pct


# --- Multi-date comparison respects the same configuration across all dates ---

def test_compare_historical_dates_applies_same_conventions_to_every_date():
    p1, p2 = _patched()
    with p1, p2:
        table = hr.compare_historical_dates(
            {"a": FIXED_DATE, "b": FIXED_DATE}, tenor_years=5,
            spot_lag_days=2, fixed_leg_daycount="ACT/360",
        )
    assert len(table) == 2
    # both rows used the same spot-lagged, ACT/360 configuration -> identical results
    # (same underlying date/data in this mocked test)
    assert table.iloc[0]["fair_rate_pct"] == pytest.approx(table.iloc[1]["fair_rate_pct"])


def test_compare_historical_dates_imm_start_resolves_per_date():
    p1, p2 = _patched()
    with p1, p2:
        table = hr.compare_historical_dates(
            {"only": FIXED_DATE}, tenor_years=5, use_imm_start=True,
        )
    assert table.iloc[0]["dv01"] > 0  # priced and repriced successfully, sane positive DV01
