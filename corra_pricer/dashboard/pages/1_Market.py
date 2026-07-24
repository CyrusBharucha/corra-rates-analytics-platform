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
        "linear": "Standard linear interpolation on zero rates, also the method used internally "
                  "during bootstrapping, so the curve reprices every GoC benchmark bond to par exactly. "
                  "Forward rates are piecewise constant, stepping at each node.",
        "log_linear_df": "Interpolates on log(discount factor), equivalent to piecewise-constant "
                         "instantaneous forward rates between nodes. Discount factors remain positive "
                         "and monotonically decreasing by construction.",
        "cubic_spline": "Fits a smooth cubic polynomial through the bootstrap nodes, producing "
                        "continuous forward rates. Visually the smoothest, but can overshoot in "
                        "sparse regions, most notably the wide 10Y-30Y gap on this curve.",
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

rate_cards = []
for label, key in [("CORRA", None), ("2Y GoC", "2Y"), ("5Y GoC", "5Y"), ("10Y GoC", "10Y")]:
    value_pct = snapshot["corra_rate_pct"] if key is None else snapshot["benchmark_yields_pct"][key]
    card = {"label": label, "value": f"{value_pct:.2f}%"}
    if key in deltas:
        d = deltas[key]
        card["delta"] = f"{d:+.1f}bp vs prior day"
        card["delta_color"] = "positive" if d >= 0 else "negative"
    elif key is None:
        card["delta"] = "overnight fixing rate"
        card["delta_color"] = "neutral"
    rate_cards.append(card)
kpi.render_kpi_row(rate_cards)

# --- Curve slope / inversion (same 4-column width as rate row above) ---
slope_2s10s = (curve.zero_rate(10) - curve.zero_rate(2)) * 10_000
slope_5s30s = (curve.zero_rate(30) - curve.zero_rate(5)) * 10_000
long_rate = snapshot["benchmark_yields_pct"]["LONG"]
long_delta = deltas.get("LONG")
long_card = {"label": "30Y GoC", "value": f"{long_rate:.2f}%"}
if long_delta is not None:
    long_card["delta"] = f"{long_delta:+.1f}bp vs prior day"
    long_card["delta_color"] = "positive" if long_delta >= 0 else "negative"
st.write("")
kpi.render_kpi_row([
    long_card,
    {"label": "2s10s Slope", "value": f"{slope_2s10s:+.1f}bp",
     "delta": "inverted" if slope_2s10s < 0 else "normal (upward-sloping)",
     "delta_color": "negative" if slope_2s10s < 0 else "positive"},
    {"label": "5s30s Slope", "value": f"{slope_5s30s:+.1f}bp",
     "delta": "inverted" if slope_5s30s < 0 else "normal (upward-sloping)",
     "delta_color": "negative" if slope_5s30s < 0 else "positive"},
    {"label": "Curve Shape", "value": "Inverted" if slope_2s10s < 0 else "Normal",
     "delta": "2s10s / 5s30s above", "delta_color": "neutral"},
])

st.write("")
tab_overview, tab_fwd, tab_interp, tab_boot, tab_meta = st.tabs(
    ["Overview", "Forward & Discount", "Interpolation Comparison", "Bootstrap Diagnostics", "Metadata"]
)

with tab_overview:
    with st.container(border=True):
        overlay_on = st.checkbox("Compare with historical curve",
                                  help="Compare today's curve against a real historical date, "
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
            }, title="GoC-Proxy OIS Zero Curve: Today vs. Historical"),
            use_container_width=True, config=charts.PLOTLY_CONFIG,
        )
    else:
        st.plotly_chart(charts.plot_yield_curve(curve, label="GoC-Proxy OIS Zero Curve"),
                         use_container_width=True, config=charts.PLOTLY_CONFIG)
    styling.render_section_label("Curve Table")
    st.table(tables.format_curve_table(curve))

with tab_fwd:
    fwd_window_label = st.radio("Forward tenor", ["3M", "6M", "1Y"], horizontal=True)
    fwd_window = {"3M": 0.25, "6M": 0.5, "1Y": 1.0}[fwd_window_label]
    st.plotly_chart(charts.plot_forward_curve(curve, max_years=29.0, window=fwd_window),
                     use_container_width=True, config=charts.PLOTLY_CONFIG)
    st.plotly_chart(charts.plot_discount_factor_curve(curve), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)

with tab_interp:
    st.caption("The same market data, bootstrapped three ways, shows where interpolation "
               "choice actually matters (mostly the sparse short end and the wide 10Y-30Y gap).")
    curves_by_method = {
        method: data_access.get_current_curve(interpolation=method)
        for method in ["linear", "log_linear_df", "cubic_spline"]
    }
    curves_by_label = {data_access.INTERPOLATION_LABELS[m]: c for m, c in curves_by_method.items()}
    st.write("")
    st.plotly_chart(charts.plot_curve_comparison(curves_by_label,
                                                    title="GoC-Proxy OIS Zero Curve: Interpolation Comparison"),
                     use_container_width=True, config=charts.PLOTLY_CONFIG)
    st.plotly_chart(
        charts.plot_interpolation_divergence(curves_by_method, labels=data_access.INTERPOLATION_LABELS),
        use_container_width=True, config=charts.PLOTLY_CONFIG,
    )

with tab_boot:
    st.caption("Validates the numerical accuracy of the bootstrapped discount curve by repricing each input bond off the final curve.")
    st.caption(
        "Each GoC benchmark bond is repriced off the final curve; the bar shows the error vs. par "
        "(should sit at/near zero). A larger residual on a non-linear-interpolated curve is real "
        "and expected, the bootstrap's internal gap solver assumes linear-on-zero-rate, so "
        "switching interpolation methods can reintroduce a small repricing error, most visible "
        "across the wide 10Y-30Y gap."
    )
    residuals = data_access.get_bootstrap_residuals(curve, snapshot["benchmark_yields_pct"])
    st.write("")
    st.plotly_chart(charts.plot_bootstrap_residuals(residuals), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)
    st.caption("Try switching the interpolation method above to see how non-linear methods introduce real repricing errors across the curve.")

with tab_meta:
    kpi.render_kpi_row([
        {"label": "Provider", "value": "Bank of Canada",
         "delta": "Valet API", "delta_color": "neutral"},
        {"label": "Curve Date", "value": str(snapshot["as_of_yields"].date()),
         "delta": "updated daily", "delta_color": "neutral"},
        {"label": "Data Frequency", "value": "Daily",
         "delta": "once per business day", "delta_color": "neutral"},
    ])
    st.write("")
    kpi.render_kpi_row([
        {"label": "Interpolation", "value": data_access.INTERPOLATION_LABELS[interpolation],
         "delta": "selected above", "delta_color": "neutral"},
        {"label": "Bootstrap", "value": "Root-Find",
         "delta": "original code, no QuantLib", "delta_color": "neutral"},
        {"label": "Discounting Source", "value": "GoC Yields",
         "delta": "OIS proxy", "delta_color": "neutral"},
    ])
    st.caption(
        "Live CORRA OIS swap quotes are not publicly available (Bloomberg/Refinitiv only), so this "
        "platform bootstraps the discounting curve from the Bank of Canada's published Government "
        "of Canada benchmark bond yields, documented and used as an OIS proxy throughout."
    )
