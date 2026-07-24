"""
Table formatters. Each function takes an already-computed backend object
and returns a display-ready pandas DataFrame - formatting only, no
computation.
"""
from __future__ import annotations

import pandas as pd


def format_curve_table(curve) -> pd.DataFrame:
    df = curve.as_dataframe().copy()
    df["tenor_years"] = df["tenor_years"].round(3)
    df["zero_rate_pct"] = df["zero_rate_pct"].round(4)
    df["discount_factor"] = df["discount_factor"].round(6)
    df.columns = ["Tenor (Y)", "Zero Rate (%)", "Discount Factor"]
    return df


def format_cashflow_table(swap) -> pd.DataFrame:
    cashflows = swap.fixed_leg_cashflows()
    df = pd.DataFrame(cashflows)
    df["accrual"] = df["accrual"].round(4)
    df["amount"] = df["amount"].round(2)
    df.columns = ["Start", "End", "Accrual (yrs)", "Fixed Cashflow ($)"]
    return df


def format_cashflow_schedule(swap, curve) -> pd.DataFrame:
    """The full fixed-leg payment schedule with discount factors and PV per
    period - the same building blocks fixed_leg_pv() already sums, just
    broken out row by row instead of collapsed to one total. Composes
    year_fraction() + curve.discount_factor(), both pre-existing public
    functions; no new pricing logic."""
    from corra_pricer.pricing_engine.conventions import year_fraction

    rows = []
    for cf in swap.fixed_leg_cashflows():
        t = year_fraction(swap.trade_date, cf["end"])
        df_t = curve.discount_factor(t)
        rows.append({
            "Accrual Start": cf["start"],
            "Accrual End": cf["end"],
            "Payment Date": cf["end"],
            "Accrual Factor (yrs)": round(cf["accrual"], 4),
            "Discount Factor": round(df_t, 6),
            "Fixed Cashflow ($)": round(cf["amount"], 2),
            "PV ($)": round(cf["amount"] * df_t, 2),
        })
    return pd.DataFrame(rows)


def format_krd_table(risk_report) -> pd.DataFrame:
    rows = [{"Bucket": k, "Key-Rate DV01 ($/bp)": round(v, 2)} for k, v in risk_report.krd.items()]
    rows.append({"Bucket": "Sum", "Key-Rate DV01 ($/bp)": round(risk_report.krd_sum(), 2)})
    rows.append({"Bucket": "Total DV01", "Key-Rate DV01 ($/bp)": round(risk_report.dv01, 2)})
    return pd.DataFrame(rows)


_SCENARIO_COLUMNS = {
    "scenario": "Scenario",
    "category": "Category",
    "npv_before": "NPV before ($)",
    "npv_after": "NPV after ($)",
    "npv_change": "NPV change ($)",
    "dv01_before": "DV01 before ($/bp)",
    "dv01_after": "DV01 after ($/bp)",
    "dv01_change": "DV01 change ($/bp)",
    "attribution_total": "KRD attribution ($)",
    "attribution_residual": "Convexity residual ($)",
}

_HISTORICAL_COLUMNS = {
    "label": "Date",
    "requested_date": "Requested",
    "data_date": "Data date",
    "fair_rate_pct": "Fair rate (%)",
    "fixed_rate_pct": "Fixed rate (%)",
    "npv": "NPV ($)",
    "dv01": "DV01 ($/bp)",
    "pv01": "PV01 ($/bp)",
    "convexity": "Convexity",
}


def _pretty_column(name: str) -> str:
    """Turn leftover engine keys (krd_2Y, curve_10Y_pct) into readable headers."""
    if name in _HISTORICAL_COLUMNS:
        return _HISTORICAL_COLUMNS[name]
    if name.startswith("krd_"):
        return f"KRD {name[4:]} ($/bp)"
    if name.startswith("curve_") and name.endswith("_pct"):
        return f"Curve {name[6:-4]} (%)"
    return name.replace("_", " ").capitalize()


def format_scenario_table(scenario_df, labeller=None, category_labels=None) -> pd.DataFrame:
    """`labeller`/`category_labels` are injected by the page so this module
    stays presentation-only and never imports the scenario catalog."""
    df = scenario_df.copy()
    for col in ["npv_change", "dv01_change", "attribution_total", "attribution_residual"]:
        if col in df.columns:
            df[col] = df[col].round(2)
    if labeller is not None and "scenario" in df.columns:
        df["scenario"] = df["scenario"].map(labeller)
    if category_labels is not None and "category" in df.columns:
        df["category"] = df["category"].map(lambda c: category_labels.get(c, c))
    df.columns = [_SCENARIO_COLUMNS.get(c, _pretty_column(c)) for c in df.columns]
    return df


def format_historical_comparison_table(comparison_df) -> pd.DataFrame:
    df = comparison_df.copy()
    round_cols = [c for c in df.columns if c not in ("label", "requested_date", "data_date")]
    for col in round_cols:
        df[col] = df[col].round(4)
    df.columns = [_pretty_column(c) for c in df.columns]
    return df
