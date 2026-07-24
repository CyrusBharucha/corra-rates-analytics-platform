"""
Thin client for the Bank of Canada Valet API (https://www.bankofcanada.ca/valet/docs).

This client pulls two data sets used throughout the platform:

1. CORRA fixings (group "CORRA", series "AVG.INTWO") - the daily overnight
   rate used for floating-leg compounding.
2. Government of Canada benchmark bond yields (group "bond_yields_benchmark")
   - used as bootstrap inputs for the discounting curve, since real CORRA OIS
   swap quotes are not published anywhere public (they live on Bloomberg /
   Refinitiv). See docs/methodology.md for the swap-spread discussion.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import requests

VALET_BASE_URL = "https://www.bankofcanada.ca/valet"

CORRA_GROUP = "CORRA"
CORRA_SERIES = "AVG.INTWO"

BENCHMARK_YIELD_GROUP = "bond_yields_benchmark"
BENCHMARK_YIELD_SERIES = {
    "2Y": "BD.CDN.2YR.DQ.YLD",
    "3Y": "BD.CDN.3YR.DQ.YLD",
    "5Y": "BD.CDN.5YR.DQ.YLD",
    "7Y": "BD.CDN.7YR.DQ.YLD",
    "10Y": "BD.CDN.10YR.DQ.YLD",
    "LONG": "BD.CDN.LONG.DQ.YLD",  # ~30Y benchmark
}


class BocValetError(RuntimeError):
    """Raised when the Valet API returns an unexpected response."""


@dataclass
class ValetRequestParams:
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    recent: int | None = None

    def as_query_params(self) -> dict:
        params: dict = {}
        if self.recent is not None:
            params["recent"] = self.recent
        if self.start_date is not None:
            params["start_date"] = self.start_date.isoformat()
        if self.end_date is not None:
            params["end_date"] = self.end_date.isoformat()
        return params


def _validate_date_range(start_date: dt.date | None, end_date: dt.date | None) -> None:
    today = dt.date.today()
    if start_date is not None and start_date > today:
        raise ValueError(f"start_date {start_date} is in the future (today is {today})")
    if end_date is not None and end_date > today:
        raise ValueError(f"end_date {end_date} is in the future (today is {today})")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError(f"start_date {start_date} is after end_date {end_date}")


def _fetch_group_observations(group: str, params: ValetRequestParams) -> dict:
    _validate_date_range(params.start_date, params.end_date)
    url = f"{VALET_BASE_URL}/observations/group/{group}/json"
    response = requests.get(url, params=params.as_query_params(), timeout=20)
    if response.status_code != 200:
        raise BocValetError(
            f"Valet API request failed for group '{group}': "
            f"HTTP {response.status_code} - {response.text[:200]}"
        )
    payload = response.json()
    if "observations" not in payload:
        raise BocValetError(f"Unexpected Valet API payload for group '{group}': {payload}")
    if len(payload["observations"]) == 0:
        raise BocValetError(f"Valet API returned zero observations for group '{group}' "
                             f"with params {params.as_query_params()}")
    return payload


def _observations_to_frame(payload: dict, series_map: dict[str, str]) -> pd.DataFrame:
    """series_map: {output_column_name: valet_series_code}"""
    rows = []
    for obs in payload["observations"]:
        row = {"date": obs["d"]}
        for out_col, series_code in series_map.items():
            cell = obs.get(series_code)
            row[out_col] = float(cell["v"]) if cell and "v" in cell else None
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").reset_index(drop=True)
    return frame


def fetch_corra_history(
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    recent: int | None = None,
) -> pd.DataFrame:
    """Returns a DataFrame with columns [date, corra] of daily CORRA fixings (in %)."""
    params = ValetRequestParams(start_date=start_date, end_date=end_date, recent=recent)
    payload = _fetch_group_observations(CORRA_GROUP, params)
    frame = _observations_to_frame(payload, {"corra": CORRA_SERIES})
    return frame.dropna(subset=["corra"]).reset_index(drop=True)


def fetch_benchmark_yields(
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    recent: int | None = None,
) -> pd.DataFrame:
    """Returns a DataFrame with columns [date, 2Y, 3Y, 5Y, 7Y, 10Y, LONG] (yields in %)."""
    params = ValetRequestParams(start_date=start_date, end_date=end_date, recent=recent)
    payload = _fetch_group_observations(BENCHMARK_YIELD_GROUP, params)
    frame = _observations_to_frame(payload, BENCHMARK_YIELD_SERIES)
    return frame


def find_missing_tenors(benchmark_yields_pct: dict) -> list[str]:
    """Returns the list of required benchmark tenors that are missing or null
    in a fetched yields dict/row. Useful before handing a snapshot to the
    curve bootstrapper, which needs every tenor present."""
    return [tenor for tenor in BENCHMARK_YIELD_SERIES if benchmark_yields_pct.get(tenor) is None]


def fetch_latest_market_snapshot() -> dict:
    """Convenience helper: latest available CORRA fixing + latest benchmark yield curve."""
    corra = fetch_corra_history(recent=1)
    yields = fetch_benchmark_yields(recent=1)
    if corra.empty or yields.empty:
        raise BocValetError("Valet API returned no recent observations.")
    return {
        "as_of_corra": corra.iloc[-1]["date"],
        "corra_rate_pct": corra.iloc[-1]["corra"],
        "as_of_yields": yields.iloc[-1]["date"],
        "benchmark_yields_pct": yields.iloc[-1].drop("date").to_dict(),
    }
