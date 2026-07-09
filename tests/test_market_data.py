import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from corra_pricer.market_data import boc_valet_client as client


def _mock_response(status_code=200, json_payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    resp.text = text
    return resp


def _corra_payload(rows: list[tuple[str, str]]) -> dict:
    return {"observations": [{"d": d, client.CORRA_SERIES: {"v": v}} for d, v in rows]}


def _yields_payload(rows: list[tuple[str, dict]]) -> dict:
    return {"observations": [{"d": d, **{k: {"v": v} for k, v in vals.items()}} for d, vals in rows]}


# --- 1. CORRA pull succeeds (live smoke test -- the one test that hits the real API) ---

def test_corra_pull_succeeds_live():
    frame = client.fetch_corra_history(recent=5)
    assert not frame.empty
    assert "corra" in frame.columns
    assert frame["corra"].notna().all()


# --- 2. Missing API response handled gracefully ---

def test_missing_observations_key_raises():
    with patch.object(client.requests, "get", return_value=_mock_response(200, {"unexpected": "payload"})):
        with pytest.raises(client.BocValetError):
            client.fetch_corra_history(recent=5)


def test_http_error_raises():
    with patch.object(client.requests, "get", return_value=_mock_response(503, {}, "service unavailable")):
        with pytest.raises(client.BocValetError):
            client.fetch_corra_history(recent=5)


# --- 3. Empty series handled ---

def test_empty_observations_raises():
    with patch.object(client.requests, "get", return_value=_mock_response(200, {"observations": []})):
        with pytest.raises(client.BocValetError):
            client.fetch_corra_history(recent=5)


# --- 4 & 5. Weekend / holiday handling: gaps in the date sequence are not errors ---

def test_weekend_gap_handled():
    # Friday, then Monday -- BoC simply doesn't publish weekend observations.
    payload = _corra_payload([("2026-07-10", "2.28"), ("2026-07-13", "2.29")])
    with patch.object(client.requests, "get", return_value=_mock_response(200, payload)):
        frame = client.fetch_corra_history(recent=5)
    assert len(frame) == 2
    assert frame["date"].tolist() == [pd_ts("2026-07-10"), pd_ts("2026-07-13")]


def test_holiday_gap_handled():
    # A multi-day gap around a holiday (e.g. Canada Day) shouldn't break parsing.
    payload = _corra_payload([("2026-06-30", "2.27"), ("2026-07-06", "2.28")])
    with patch.object(client.requests, "get", return_value=_mock_response(200, payload)):
        frame = client.fetch_corra_history(recent=5)
    assert len(frame) == 2


def pd_ts(s):
    import pandas as pd
    return pd.Timestamp(s)


# --- 6. Most recent observation selected correctly ---

def test_most_recent_observation_selected_even_if_unsorted():
    payload = _corra_payload([("2026-07-08", "2.20"), ("2026-07-10", "2.30"), ("2026-07-09", "2.25")])
    with patch.object(client.requests, "get", return_value=_mock_response(200, payload)):
        frame = client.fetch_corra_history(recent=5)
    assert frame.iloc[-1]["date"] == pd_ts("2026-07-10")
    assert frame.iloc[-1]["corra"] == pytest.approx(2.30)


# --- 7. Future dates rejected ---

def test_future_start_date_rejected():
    future = dt.date.today() + dt.timedelta(days=5)
    with pytest.raises(ValueError):
        client.fetch_corra_history(start_date=future)


def test_future_end_date_rejected():
    future = dt.date.today() + dt.timedelta(days=5)
    with pytest.raises(ValueError):
        client.fetch_corra_history(end_date=future)


def test_start_after_end_rejected():
    today = dt.date.today()
    with pytest.raises(ValueError):
        client.fetch_corra_history(start_date=today, end_date=today - dt.timedelta(days=10))


# --- 8. Missing tenor detection ---

def test_missing_tenor_detected():
    partial = {"2Y": 2.8, "3Y": 2.91, "5Y": None, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
    missing = client.find_missing_tenors(partial)
    assert missing == ["5Y"]


def test_no_missing_tenor_when_complete():
    complete = {"2Y": 2.8, "3Y": 2.91, "5Y": 3.12, "7Y": 3.26, "10Y": 3.52, "LONG": 3.93}
    assert client.find_missing_tenors(complete) == []


# --- 9. Negative rates accepted ---

def test_negative_rates_accepted():
    payload = _corra_payload([("2026-07-10", "-0.25")])
    with patch.object(client.requests, "get", return_value=_mock_response(200, payload)):
        frame = client.fetch_corra_history(recent=1)
    assert frame.iloc[-1]["corra"] == pytest.approx(-0.25)


# --- 10. Extremely high rates accepted ---

def test_extremely_high_rates_accepted():
    payload = _corra_payload([("2026-07-10", "45.00")])
    with patch.object(client.requests, "get", return_value=_mock_response(200, payload)):
        frame = client.fetch_corra_history(recent=1)
    assert frame.iloc[-1]["corra"] == pytest.approx(45.0)
