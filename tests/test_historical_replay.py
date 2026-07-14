import datetime as dt
from unittest.mock import patch

import pandas as pd
import pytest

from corra_pricer.analytics import historical_replay as hr
from corra_pricer.curve_builder.curve import YieldCurve
from corra_pricer.market_data import boc_valet_client as client
from corra_pricer.pricing_engine.ois_swap import CorraOISSwap
from corra_pricer.risk_engine.risk_report import RiskReport


# ---------------------------------------------------------------------------
# Deterministic tests: mock the market-data layer so nearest-date resolution
# and error handling don't depend on what happens to be published today.
# ---------------------------------------------------------------------------

def _corra_frame(rows):
    return pd.DataFrame({"date": [pd.Timestamp(d) for d, _ in rows], "corra": [v for _, v in rows]})


def _yields_frame(rows):
    data = {"date": [pd.Timestamp(d) for d, _ in rows]}
    tenors = ["2Y", "3Y", "5Y", "7Y", "10Y", "LONG"]
    for i, t in enumerate(tenors):
        data[t] = [vals[i] for _, vals in rows]
    return pd.DataFrame(data)


def test_nearest_date_fallback_on_weekend_gap():
    """Requesting a Sunday (no publication) should resolve to the most
    recent prior business day's data. The mock only returns rows a real
    end_date=2026-07-12 query would actually return (i.e. nothing from the
    following Monday) -- fetch_market_snapshot_for_date's job is simply to
    take the last (most recent) row of whatever the API gives back within
    the window, which this test isolates from the real API's own filtering."""
    corra_rows = [("2026-07-09", 2.27), ("2026-07-10", 2.28)]  # Thu, Fri
    yields_rows = [("2026-07-09", [2.79, 2.90, 3.10, 3.25, 3.51, 3.92]),
                    ("2026-07-10", [2.8, 2.9, 3.1, 3.2, 3.5, 3.9])]
    with patch.object(hr, "fetch_corra_history", return_value=_corra_frame(corra_rows)), \
         patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(yields_rows)):
        snapshot = hr.fetch_market_snapshot_for_date(dt.date(2026, 7, 12))  # the Sunday after
    assert snapshot["corra_data_date"] == dt.date(2026, 7, 10)
    assert snapshot["yields_data_date"] == dt.date(2026, 7, 10)
    assert snapshot["corra_pct"] == pytest.approx(2.28)


def test_no_data_in_window_raises():
    with patch.object(hr, "fetch_corra_history", return_value=pd.DataFrame(columns=["date", "corra"])), \
         patch.object(hr, "fetch_benchmark_yields",
                       return_value=pd.DataFrame(columns=["date", "2Y", "3Y", "5Y", "7Y", "10Y", "LONG"])):
        with pytest.raises(client.BocValetError):
            hr.fetch_market_snapshot_for_date(dt.date(1990, 1, 1))


def test_build_historical_curve_uses_bootstrap_zero_curve():
    corra_rows = [("2026-07-10", 2.29)]
    yields_rows = [("2026-07-10", [2.80, 2.91, 3.12, 3.26, 3.52, 3.93])]
    with patch.object(hr, "fetch_corra_history", return_value=_corra_frame(corra_rows)), \
         patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(yields_rows)):
        curve, snapshot = hr.build_historical_curve(dt.date(2026, 7, 10))
    assert isinstance(curve, YieldCurve)
    assert curve.discount_factor(0) == pytest.approx(1.0)
    assert snapshot["corra_pct"] == pytest.approx(2.29)


def test_price_swap_as_of_reuses_existing_pricer_and_risk_engine():
    """price_swap_as_of should produce a swap/curve/risk-report indistinguishable
    from calling the Module 2/3/4 functions directly -- no parallel logic."""
    corra_rows = [("2026-07-10", 2.29)]
    yields_rows = [("2026-07-10", [2.80, 2.91, 3.12, 3.26, 3.52, 3.93])]
    with patch.object(hr, "fetch_corra_history", return_value=_corra_frame(corra_rows)), \
         patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(yields_rows)):
        result = hr.price_swap_as_of(dt.date(2026, 7, 10), tenor_years=5, notional=10_000_000)

    assert isinstance(result.swap, CorraOISSwap)
    assert isinstance(result.risk, RiskReport)
    assert result.swap.trade_date == dt.date(2026, 7, 10)
    assert result.swap.effective_date == dt.date(2026, 7, 10)
    assert result.swap.maturity_date == dt.date(2031, 7, 10)
    # priced at fair rate by default -> NPV should be ~0, exactly like Module 3's fair_rate() contract
    assert result.npv == pytest.approx(0.0, abs=1.0)
    assert result.risk.dv01 > 0  # pay_fixed default


def test_price_swap_as_of_with_explicit_fixed_rate_gives_nonzero_npv():
    corra_rows = [("2026-07-10", 2.29)]
    yields_rows = [("2026-07-10", [2.80, 2.91, 3.12, 3.26, 3.52, 3.93])]
    with patch.object(hr, "fetch_corra_history", return_value=_corra_frame(corra_rows)), \
         patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(yields_rows)):
        result = hr.price_swap_as_of(dt.date(2026, 7, 10), tenor_years=5, fixed_rate=0.03)
    assert result.swap.fixed_rate == 0.03
    assert result.npv != pytest.approx(0.0, abs=1.0)


def test_compare_historical_dates_with_dict_labels():
    corra_rows = [("2026-07-08", 2.20), ("2026-07-10", 2.29)]
    yields_rows = [("2026-07-08", [2.70, 2.80, 3.00, 3.10, 3.40, 3.80]),
                    ("2026-07-10", [2.80, 2.91, 3.12, 3.26, 3.52, 3.93])]
    with patch.object(hr, "fetch_corra_history", return_value=_corra_frame(corra_rows)), \
         patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(yields_rows)):
        table = hr.compare_historical_dates(
            {"date_a": dt.date(2026, 7, 8), "date_b": dt.date(2026, 7, 10)}, tenor_years=5,
        )
    assert list(table["label"]) == ["date_a", "date_b"]
    assert len(table) == 2
    for col in ["npv", "dv01", "pv01", "convexity", "krd_2Y", "krd_5Y", "krd_10Y", "krd_30Y", "fair_rate_pct"]:
        assert col in table.columns


def test_compare_historical_dates_with_list_uses_isoformat_labels():
    corra_rows = [("2026-07-10", 2.29)]
    yields_rows = [("2026-07-10", [2.80, 2.91, 3.12, 3.26, 3.52, 3.93])]
    with patch.object(hr, "fetch_corra_history", return_value=_corra_frame(corra_rows)), \
         patch.object(hr, "fetch_benchmark_yields", return_value=_yields_frame(yields_rows)):
        table = hr.compare_historical_dates([dt.date(2026, 7, 10)], tenor_years=5)
    assert table.iloc[0]["label"] == "2026-07-10"


# ---------------------------------------------------------------------------
# Live tests against the real BoC Valet API -- confirms the pipeline works
# end to end on real historical data, not just mocks.
# ---------------------------------------------------------------------------

def test_march_2020_prices_off_real_covid_era_curve_live():
    result = hr.price_swap_as_of(hr.EXAMPLE_DATES["march_2020"], tenor_years=5)
    # BoC cut to 0.25% in March 2020 -- a 5Y fair rate should be low-single-digit-bp to low-percent.
    assert 0.0 < result.fair_rate_pct < 2.0
    assert result.npv == pytest.approx(0.0, abs=5.0)


def test_october_2023_curve_is_inverted_live():
    """October 2023 is a well-documented inverted-curve period for GoC/CORRA --
    confirms the historical bootstrap correctly reproduces real curve shape,
    not just synthetic test curves (see test_bootstrap.py::test_inverted_curve_handled)."""
    curve, _ = hr.build_historical_curve(hr.EXAMPLE_DATES["october_2023"])
    assert curve.zero_rate(2) > curve.zero_rate(10)


def test_rates_rose_from_2020_to_2022_to_2023_live():
    """Sanity-checks the historical pipeline against known real history: the
    BoC's overnight rate went from emergency-low in March 2020 to actively
    hiking by March 2022 to near cycle-peak by October 2023 -- fair rates
    for a 5Y swap struck on each date should reflect that."""
    r_2020 = hr.price_swap_as_of(hr.EXAMPLE_DATES["march_2020"], tenor_years=5)
    r_2022 = hr.price_swap_as_of(hr.EXAMPLE_DATES["march_2022"], tenor_years=5)
    r_2023 = hr.price_swap_as_of(hr.EXAMPLE_DATES["october_2023"], tenor_years=5)
    assert r_2020.fair_rate_pct < r_2022.fair_rate_pct < r_2023.fair_rate_pct


def test_compare_example_dates_live():
    table = hr.compare_example_dates(tenor_years=5, include_today=True)
    assert len(table) == len(hr.EXAMPLE_DATES) + 1  # every timeline checkpoint, plus "today"
    assert set(table["label"]) == set(hr.EXAMPLE_DATES.keys()) | {"today"}
    assert table["dv01"].apply(lambda v: v > 0).all()  # default pay_fixed=True
