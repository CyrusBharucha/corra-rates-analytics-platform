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

styling.apply_page_config("Scenarios")
styling.render_header("Scenarios",
                       "40+ parallel shifts, curve trades, and macro-event stress tests, plus "
                       "user-defined shocks and Monte Carlo")

if "priced_swap" not in st.session_state:
    st.info("No swap has been priced yet on the **Pricing** page -- showing a default "
             "5Y, $10mm, pay-fixed swap at the current fair rate instead.")
    curve = data_access.get_current_curve(interpolation="linear")
    trade_date = dt.date.today()
    maturity_date = data_access.maturity_from_tenor(trade_date, 5)
    swap = data_access.build_swap(trade_date, maturity_date, 10_000_000, 0.0, True)
    swap.fixed_rate = swap.fair_rate(curve)
else:
    swap = st.session_state["priced_swap"]
    curve = st.session_state["pricing_curve"]

st.caption(
    f"{'Pay' if swap.pay_fixed else 'Receive'} Fixed &middot; ${swap.notional:,.0f} notional &middot; "
    f"{swap.fixed_rate * 100:.4f}% fixed &middot; matures {swap.maturity_date.isoformat()}",
    unsafe_allow_html=True,
)

tab_detail, tab_grid, tab_custom, tab_mc = st.tabs(
    ["Scenario Detail", "Full Grid", "Custom Shock", "Monte Carlo"]
)

with tab_detail:
    scenario_names = data_access.get_scenario_names()
    catalog = data_access.get_scenario_catalog()
    selected = st.selectbox(
        "Scenario", scenario_names, format_func=data_access.scenario_option_label,
    )
    # The parallel-shift descriptions already say "Parallel curve shift, ...",
    # so prefixing the category there just repeats the word.
    _category = catalog[selected].category
    _badge = "" if _category == "parallel" else (
        f"**{data_access.SCENARIO_CATEGORY_LABELS.get(_category, '')}** &middot; "
    )
    st.caption(f"{_badge}{catalog[selected].description}", unsafe_allow_html=True)

    result = data_access.get_scenario_detail(swap, curve, selected)
    scenario_curve = data_access.get_scenario_curve(curve, selected)

    kpi.render_kpi_row([
        {"label": "NPV Before", "value": kpi.money(result.npv_before)},
        {"label": "NPV After", "value": kpi.money(result.npv_after),
         "delta": f"{'+' if result.npv_change >= 0 else ''}${result.npv_change:,.0f}",
         "delta_color": "positive" if result.npv_change >= 0 else "negative"},
        {"label": "DV01 Change", "value": f"${result.dv01_change:,.2f}"},
        {"label": "Convexity Residual", "value": f"${result.attribution_residual:,.2f}",
         "delta": "actual reprice vs. linear KRD estimate", "delta_color": "neutral"},
    ])

    col1, col2 = st.columns(2)
    with col1:
        styling.render_section_label("Curve Before / After")
        st.plotly_chart(
            charts.plot_curve_comparison({
                "Base curve": curve,
                f"{data_access.scenario_display_name(selected)} (shocked)": scenario_curve,
            }),
            use_container_width=True, config=charts.PLOTLY_CONFIG,
        )
    with col2:
        styling.render_section_label("P&L Attribution")
        st.plotly_chart(charts.plot_scenario_waterfall(result), use_container_width=True,
                         config=charts.PLOTLY_CONFIG)

with tab_grid:
    scenario_table = data_access.get_scenario_table(swap, curve)
    st.plotly_chart(
        charts.plot_scenario_grid(scenario_table, labeller=data_access.scenario_display_name),
        use_container_width=True, config=charts.PLOTLY_CONFIG,
    )
    st.dataframe(
        tables.format_scenario_table(
            scenario_table,
            labeller=data_access.scenario_display_name,
            category_labels=data_access.SCENARIO_CATEGORY_LABELS,
        ),
        use_container_width=True, hide_index=True,
    )

with tab_custom:
    st.caption("Define your own key-rate shock (in bp) at each bucket and reprice against it.")
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            shock_2y = st.number_input("2Y shock (bp)", value=0.0, step=1.0)
        with col2:
            shock_5y = st.number_input("5Y shock (bp)", value=0.0, step=1.0)
        with col3:
            shock_10y = st.number_input("10Y shock (bp)", value=0.0, step=1.0)
        with col4:
            shock_30y = st.number_input("30Y shock (bp)", value=0.0, step=1.0)

    custom_shocks = {2.0: shock_2y, 5.0: shock_5y, 10.0: shock_10y, 30.0: shock_30y}
    custom_result = data_access.get_custom_scenario_result(swap, curve, custom_shocks)
    custom_curve = data_access.get_custom_scenario_curve(curve, custom_shocks)

    kpi.render_kpi_row([
        {"label": "NPV Before", "value": kpi.money(custom_result.npv_before)},
        {"label": "NPV After", "value": kpi.money(custom_result.npv_after),
         "delta": f"{'+' if custom_result.npv_change >= 0 else ''}${custom_result.npv_change:,.0f}",
         "delta_color": "positive" if custom_result.npv_change >= 0 else "negative"},
        {"label": "DV01 Change", "value": f"${custom_result.dv01_change:,.2f}"},
    ])
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(
            charts.plot_curve_comparison({"Base curve": curve, "Custom shock": custom_curve}),
            use_container_width=True, config=charts.PLOTLY_CONFIG,
        )
    with col2:
        st.plotly_chart(charts.plot_scenario_waterfall(custom_result), use_container_width=True,
                         config=charts.PLOTLY_CONFIG)

with tab_mc:
    st.caption(
        "Draws independent random shocks at each bucket from a Normal(0, std) distribution and "
        "fully reprices the swap under each draw, showing the resulting P&L distribution. Buckets "
        "are shocked independently (a simplification -- real curve moves are correlated across "
        "tenors), so treat this as exploring unstructured curve noise, not a calibrated risk model."
    )
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            n_sims = st.slider("Number of simulations", min_value=50, max_value=2000, value=500, step=50)
        with col2:
            shock_std = st.slider("Shock std dev per bucket (bp)", min_value=1.0, max_value=100.0,
                                   value=25.0, step=1.0)
        with col3:
            seed = st.number_input("Random seed", min_value=0, value=42, step=1)

    mc = data_access.get_monte_carlo_results(swap, curve, n_sims, shock_std, seed)
    kpi.render_kpi_row([
        {"label": "Mean P&L", "value": f"${mc['npv_change'].mean():,.0f}"},
        {"label": "P&L Std Dev", "value": f"${mc['npv_change'].std():,.0f}"},
        {"label": "5th Percentile", "value": f"${mc['npv_change'].quantile(0.05):,.0f}",
         "delta": "worst-case tail of THIS simulated distribution, not a calibrated VaR",
         "delta_color": "neutral"},
        {"label": "95th Percentile", "value": f"${mc['npv_change'].quantile(0.95):,.0f}"},
    ])
    st.plotly_chart(charts.plot_monte_carlo_histogram(mc), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)
