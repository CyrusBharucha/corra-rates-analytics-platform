import datetime as dt
import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "corra_pricer").is_dir() and (parent / "requirements.txt").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Could not locate the project root (expected a 'corra_pricer' package "
                        "and requirements.txt in a parent directory).")


_ensure_project_root_on_path()

import streamlit as st

from corra_pricer.dashboard.components import charts, data_access, kpi, styling, tables

styling.apply_page_config("Historical Replay")
styling.render_header("Historical Replay",
                       "Price the same swap across a real, multi-year rates timeline")

EXAMPLES = data_access.EXAMPLE_HISTORICAL_DATES  # already chronologically ordered
PRESET_TITLES = {
    "march_2020": "March 2020 (COVID crash)",
    "qe_2020": "June 2020 (QE in full swing)",
    "recovery_2021": "September 2021 (post-COVID recovery)",
    "march_2022": "March 2022 (eve of first hike)",
    "inflation_peak_2022": "July 2022 (surprise 100bp hike)",
    "hiking_peak_2023": "July 2023 (cycle's 5.00% terminal rate)",
    "october_2023": "October 2023 (\"higher for longer\" repricing)",
    "first_cut_2024": "June 2024 (first cut of the easing cycle)",
    "mid_2025": "January 2025 (a year into easing)",
}
PRESETS = {PRESET_TITLES[key]: date for key, date in EXAMPLES.items()}
PRESETS["Today"] = dt.date.today()

styling.render_section_label("Select Dates to Compare")
with st.container(border=True):
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_presets = st.multiselect(
            "Historical checkpoints", list(PRESETS.keys()), default=list(PRESETS.keys()),
        )
    with col2:
        include_custom = st.checkbox("Add a custom date")

    dates = {label: PRESETS[label] for label in selected_presets}
    if include_custom:
        custom_date = st.date_input("Custom date", value=dt.date(2023, 3, 13), key="custom_hist_date")
        dates[f"Custom ({custom_date.isoformat()})"] = custom_date

if len(dates) < 2:
    st.warning("Select at least two dates to compare.")
    st.stop()

styling.render_section_label("Swap Terms")
with st.container(border=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        tenor_label = st.selectbox("Tenor", list(data_access.TENORS_YEARS.keys()), index=3, key="hist_tenor")
    with col2:
        notional = st.number_input("Notional ($)", min_value=1_000, value=10_000_000,
                                    step=100_000, key="hist_notional")
    with col3:
        pay_fixed = st.radio("Direction", ["Pay Fixed", "Receive Fixed"], key="hist_dir") == "Pay Fixed"

    col4, col5 = st.columns(2)
    with col4:
        spot_lag_label = st.selectbox("Spot lag", ["T+0", "T+1", "T+2"], index=0, key="hist_spot_lag",
                                       help="Business days from each as-of date to that date's own "
                                            "effective date, skipping weekends/holidays on the Canada "
                                            "calendar. Applied identically to every checkpoint.")
        spot_lag_days = int(spot_lag_label[2:])
    with col5:
        start_type = st.radio("Start type", ["Spot Start", "IMM Start"], horizontal=True, key="hist_start_type",
                               help="IMM Start resolves the next IMM date (3rd Wednesday of "
                                    "Mar/Jun/Sep/Dec) separately for each checkpoint, so every date "
                                    "compares the same *kind* of swap rather than one shared date.")
        use_imm_start = start_type == "IMM Start"

    with st.expander("Advanced Settings"):
        daycount = st.selectbox("Fixed leg day count", data_access.DAYCOUNT_CHOICES, key="hist_daycount",
                                 help="ACT/365F: actual days / 365 (CORRA OIS market standard). "
                                      "ACT/360: actual days / 360 (money-market convention). "
                                      "30/360: each month counted as 30 days (bond-basis). "
                                      "ACT/ACT: actual days / actual days in each calendar year (ISDA).")
        stub = st.selectbox("Stub", data_access.STUB_CHOICES, key="hist_stub",
                             format_func=lambda s: data_access.STUB_LABELS[s],
                             help="Where the odd (non-whole-period) leftover sits when the tenor "
                                  "doesn't divide evenly.")
        bdc = st.selectbox("Business day convention", data_access.BUSINESS_DAY_CONVENTION_CHOICES,
                            key="hist_bdc",
                            help="How a payment date that lands on a weekend/holiday gets moved to a "
                                 "real business day.")
        calendar_name = st.selectbox(
            "Calendar", data_access.CALENDAR_CHOICES, key="hist_calendar",
            index=0 if bdc != "None" else data_access.CALENDAR_CHOICES.index("Weekend Only"),
        )
    st.caption("Every date in the comparison below uses this exact same swap configuration -- the "
               "same swap, compared through time.")

tenor_years = data_access.TENORS_YEARS[tenor_label]
conventions = dict(
    fixed_leg_daycount=daycount, business_day_convention=bdc, calendar_name=calendar_name,
    stub=stub, spot_lag_days=spot_lag_days, use_imm_start=use_imm_start,
)

try:
    curves = {}
    for label, date in dates.items():
        curve, snapshot = data_access.get_historical_curve(date)
        curves[f"{label} ({snapshot['yields_data_date']})"] = curve
except Exception as exc:
    st.error(f"Could not fetch historical data for one of these dates: {exc}")
    st.stop()

comparison = data_access.compare_historical_dates(dates, tenor_years, notional,
                                                    fixed_rate=None, pay_fixed=pay_fixed, **conventions)

fair_rates = comparison["fair_rate_pct"]
kpi.render_kpi_row([
    {"label": "Lowest Fair Rate", "value": f"{fair_rates.min():.4f}%",
     "delta": comparison.loc[fair_rates.idxmin(), "label"], "delta_color": "neutral"},
    {"label": "Highest Fair Rate", "value": f"{fair_rates.max():.4f}%",
     "delta": comparison.loc[fair_rates.idxmax(), "label"], "delta_color": "neutral"},
    {"label": "Range", "value": f"{fair_rates.max() - fair_rates.min():.4f}%",
     "delta": f"across {len(dates)} dates", "delta_color": "neutral"},
])

tab_animation, tab_compare, tab_heatmap, tab_timeline = st.tabs(
    ["Curve Animation", "Curve Comparison", "Risk Through Time", "Fair Rate & DV01 Timeline"]
)

with tab_animation:
    st.caption("Press Play to watch the yield curve evolve across the selected dates, or drag the "
               "slider to step through manually.")
    st.plotly_chart(charts.plot_curve_animation(curves), use_container_width=True, config=charts.PLOTLY_CONFIG)

with tab_compare:
    st.plotly_chart(charts.plot_curve_comparison(curves), use_container_width=True, config=charts.PLOTLY_CONFIG)
    st.plotly_chart(charts.plot_npv_dv01_comparison(comparison), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)
    st.dataframe(tables.format_historical_comparison_table(comparison), use_container_width=True,
                 hide_index=True)

with tab_heatmap:
    st.caption(
        "Key-rate DV01 for the same swap terms, struck fresh on each historical date -- shows how "
        "risk concentration itself shifted as the curve moved through the cycle."
    )
    heatmap_data = data_access.get_historical_krd_heatmap(dates, tenor_years, notional, None, pay_fixed,
                                                            **conventions)
    st.plotly_chart(
        charts.plot_krd_heatmap(heatmap_data, title="Key-Rate DV01 Through Time",
                                 row_label="Date", row_hover_label="Date"),
        use_container_width=True, config=charts.PLOTLY_CONFIG,
    )

with tab_timeline:
    st.plotly_chart(charts.plot_metric_timeline(comparison), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)
