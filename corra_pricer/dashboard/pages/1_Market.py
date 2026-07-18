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

styling.apply_page_config("Market")
styling.render_header("Market", "Live CORRA fixing and Government of Canada benchmark yield curve")

styling.render_section_label("Curve Settings")
with st.container(border=True):
    interpolation = st.radio(
        "Curve interpolation method", ["linear", "log_linear_df", "cubic_spline"], horizontal=True,
        format_func=lambda m: data_access.INTERPOLATION_LABELS[m],
        help="How zero rates are interpolated between bootstrap nodes. See the Interpolation "
             "Comparison tab below to compare all three on the same data.",
    )
    _INTERPOLATION_NOTES = {
        "linear": "Draws a straight line between adjacent zero-rate nodes. The market standard "
                  "and the method the bootstrap itself assumes internally, so the curve reprices "
                  "every input bond to par exactly. Forward rates are piecewise constant, which "
                  "makes them step at each node.",
        "log_linear_df": "Interpolates linearly on the log of the discount factor rather than on "
                         "the zero rate, which is equivalent to holding the forward rate constant "
                         "between nodes. Guarantees discount factors stay positive and decreasing, "
                         "so it cannot produce a negative forward rate.",
        "cubic_spline": "Fits a smooth cubic polynomial through the nodes, giving continuous "
                        "forward rates instead of steps. The smoothest visually, but it can "
                        "overshoot between widely spaced nodes, most visibly across the 10Y to "
                        "30Y gap where there is no data in between.",
    }
    st.caption(
        f"**{data_access.INTERPOLATION_LABELS[interpolation]}.** "
        f"{_INTERPOLATION_NOTES[interpolation]}"
    )

snapshot = data_access.get_market_snapshot()
curve = data_access.get_current_curve(interpolation=interpolation)

st.caption(
    f"CORRA as of {snapshot['as_of_corra'].date()} &middot; "
    f"GoC benchmark yields as of {snapshot['as_of_yields'].date()}",
    unsafe_allow_html=True,
)

# --- Yield-change-today deltas vs. the prior available business day ---
deltas = {}
try:
    prior = data_access.get_prior_day_snapshot()
    for tenor in ["2Y", "5Y", "10Y", "LONG"]:
        deltas[tenor] = (snapshot["benchmark_yields_pct"][tenor] - prior["yields_pct"][tenor]) * 100  # pp -> bp
except Exception:
    pass  # deltas are a nice-to-have; degrade gracefully if the extra lookup fails

kpi_cards = []
for label, key in [("CORRA", None), ("2Y GoC", "2Y"), ("5Y GoC", "5Y"), ("10Y GoC", "10Y"), ("30Y GoC", "LONG")]:
    value_pct = snapshot["corra_rate_pct"] if key is None else snapshot["benchmark_yields_pct"][key]
    card = {"label": label, "value": f"{value_pct:.2f}%"}
    if key in deltas:
        d = deltas[key]
        card["delta"] = f"{d:+.1f}bp vs prior day"
        card["delta_color"] = "positive" if d >= 0 else "negative"
    kpi_cards.append(card)
kpi.render_kpi_row(kpi_cards)

# --- Curve slope / inversion ---
slope_2s10s = (curve.zero_rate(10) - curve.zero_rate(2)) * 10_000
slope_5s30s = (curve.zero_rate(30) - curve.zero_rate(5)) * 10_000
st.write("")
kpi.render_kpi_row([
    {"label": "2s10s Slope", "value": f"{slope_2s10s:+.1f}bp",
     "delta": "inverted" if slope_2s10s < 0 else "normal (upward-sloping)",
     "delta_color": "negative" if slope_2s10s < 0 else "positive"},
    {"label": "5s30s Slope", "value": f"{slope_5s30s:+.1f}bp",
     "delta": "inverted" if slope_5s30s < 0 else "normal (upward-sloping)",
     "delta_color": "negative" if slope_5s30s < 0 else "positive"},
    {"label": "Curve Shape", "value": "Inverted" if slope_2s10s < 0 else "Normal"},
])

st.write("")
tab_overview, tab_fwd, tab_interp, tab_boot, tab_meta = st.tabs(
    ["Overview", "Forward & Discount", "Interpolation Comparison", "Bootstrap Diagnostics", "Metadata"]
)

with tab_overview:
    with st.container(border=True):
        overlay_on = st.checkbox("Overlay a historical curve",
                                  help="Compare today's curve against a real historical date -- "
                                       "see the Historical Replay page for a full multi-date timeline.")
        if overlay_on:
            preset_map = {
                "March 2020 (COVID easing)": data_access.EXAMPLE_HISTORICAL_DATES["march_2020"],
                "March 2022 (eve of first hike)": data_access.EXAMPLE_HISTORICAL_DATES["march_2022"],
                "October 2023 (cycle peak)": data_access.EXAMPLE_HISTORICAL_DATES["october_2023"],
            }
            preset_label = st.selectbox("Overlay date", list(preset_map.keys()))
    if overlay_on:
        overlay_date = preset_map[preset_label]
        overlay_curve, overlay_snapshot = data_access.get_historical_curve(overlay_date)
        st.plotly_chart(
            charts.plot_curve_comparison({
                "Today": curve,
                f"{preset_label} ({overlay_snapshot['yields_data_date']})": overlay_curve,
            }),
            use_container_width=True, config=charts.PLOTLY_CONFIG,
        )
    else:
        st.plotly_chart(charts.plot_yield_curve(curve, label="GoC-proxy OIS curve"),
                         use_container_width=True, config=charts.PLOTLY_CONFIG)
    styling.render_section_label("Curve Table")
    st.dataframe(tables.format_curve_table(curve), use_container_width=True, hide_index=True)

with tab_fwd:
    fwd_window_label = st.radio("Forward tenor", ["3M", "6M", "1Y"], horizontal=True)
    fwd_window = {"3M": 0.25, "6M": 0.5, "1Y": 1.0}[fwd_window_label]
    st.plotly_chart(charts.plot_forward_curve(curve, max_years=29.0, window=fwd_window),
                     use_container_width=True, config=charts.PLOTLY_CONFIG)
    st.plotly_chart(charts.plot_discount_factor_curve(curve), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)

with tab_interp:
    st.caption("The same market data, bootstrapped three ways -- shows where interpolation "
               "choice actually matters (mostly the sparse short end and the wide 10Y-30Y gap).")
    curves_by_method = {
        method: data_access.get_current_curve(interpolation=method)
        for method in ["linear", "log_linear_df", "cubic_spline"]
    }
    curves_by_label = {data_access.INTERPOLATION_LABELS[m]: c for m, c in curves_by_method.items()}
    st.plotly_chart(charts.plot_curve_comparison(curves_by_label), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)
    st.plotly_chart(
        charts.plot_interpolation_divergence(curves_by_method, labels=data_access.INTERPOLATION_LABELS),
        use_container_width=True, config=charts.PLOTLY_CONFIG,
    )

with tab_boot:
    st.caption(
        "Quality-control view: reprices each Government of Canada benchmark bond that went into "
        "the bootstrap, off the final curve, and shows the error vs. par (should sit at/near "
        "zero). A larger residual on a non-linear-interpolated curve is real and expected -- the "
        "bootstrap's internal gap solver always assumes linear-on-zero-rate, so switching the "
        "curve's final interpolation method can reintroduce a small repricing error, most "
        "visible across the wide 10Y-to-30Y gap."
    )
    residuals = data_access.get_bootstrap_residuals(curve, snapshot["benchmark_yields_pct"])
    st.plotly_chart(charts.plot_bootstrap_residuals(residuals), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)

with tab_meta:
    kpi.render_kpi_row([
        {"label": "Provider", "value": "Bank of Canada Valet API"},
        {"label": "Curve Date", "value": str(snapshot["as_of_yields"].date())},
        {"label": "Last Refresh", "value": "cached up to 1 hour"},
    ])
    st.write("")
    kpi.render_kpi_row([
        {"label": "Interpolation", "value": data_access.INTERPOLATION_LABELS[interpolation]},
        {"label": "Bootstrap Method", "value": "Manual root-find (brentq), no QuantLib"},
        {"label": "Discounting Source", "value": "GoC benchmark yields (OIS proxy)"},
    ])
    st.caption(
        "Live CORRA OIS swap quotes are not publicly available (Bloomberg/Refinitiv only), so this "
        "platform bootstraps the discounting curve from the Bank of Canada's published Government "
        "of Canada benchmark bond yields, documented and used as an OIS proxy throughout."
    )
