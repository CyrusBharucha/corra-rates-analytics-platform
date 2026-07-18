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

styling.apply_page_config("Risk")
styling.render_header("Risk", "DV01, PV01, key-rate DV01, duration, and convexity for the priced swap")

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

risk = data_access.get_risk_report(swap, curve)
extended = data_access.get_extended_risk_metrics(swap, curve)

kpi.render_kpi_row([
    {"label": "DV01", "value": f"${risk.dv01:,.2f}",
     "delta": "per +1bp parallel shift (≡ IR01)", "delta_color": "neutral",
     "help": "Dollar Value of a 01 (basis point): how much NPV changes for a 1bp parallel move "
             "in the curve. The primary hedge ratio a rates desk trades against."},
    {"label": "PV01", "value": f"${risk.pv01:,.2f}",
     "delta": "value of 1bp on the annuity", "delta_color": "neutral",
     "help": "Present Value of a 01: the dollar value of 1bp on the fixed leg's annuity alone -- "
             "a leg-level building block, distinct from DV01's net (both-legs) sensitivity."},
    {"label": "Convexity", "value": f"${risk.convexity:,.4f}",
     "delta": "$ per (1bp)^2", "delta_color": "neutral",
     "help": "Second-order sensitivity: how much DV01 itself changes as rates move. DV01 is a "
             "linear (1st-order) approximation; convexity captures the curvature it misses."},
    {"label": "Dollar Duration", "value": f"${extended['dollar_duration_100bp']:,.0f}",
     "delta": "per 100bp parallel shift", "delta_color": "neutral",
     "help": "DV01 scaled to a full 1% move: the approximate dollar change in NPV for a 100bp "
             "parallel shift in the curve."},
])

st.write("")
tab_krd, tab_duration, tab_leg, tab_heatmap = st.tabs(
    ["Key-Rate DV01", "Duration & Gamma", "Risk by Leg", "Risk Heatmap"]
)

with tab_krd:
    st.caption("**KRD (Key-Rate DV01)**: DV01 broken out by curve bucket (2Y/5Y/10Y/30Y) instead of "
               "one parallel number -- shows *where* on the curve the risk actually sits.")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.dataframe(tables.format_krd_table(risk), use_container_width=True, hide_index=True)
    with col2:
        st.plotly_chart(charts.plot_krd_waterfall(risk), use_container_width=True, config=charts.PLOTLY_CONFIG)
    st.plotly_chart(charts.plot_krd_bar(risk), use_container_width=True, config=charts.PLOTLY_CONFIG)

    total = risk.dv01 if risk.dv01 != 0 else 1.0
    contribution_pct = {bucket: (val / total) * 100 for bucket, val in risk.krd.items()}
    st.caption("Risk contribution %: " + " · ".join(f"{b} {p:.1f}%" for b, p in contribution_pct.items()))

with tab_duration:
    kpi.render_kpi_row([
        {"label": "Dollar Duration (100bp)", "value": f"${extended['dollar_duration_100bp']:,.0f}",
         "delta": "true 100bp reprice, not 100x the 1bp DV01", "delta_color": "neutral"},
        {"label": "Gamma DV01 (50bp)", "value": f"${extended['gamma_dv01_50bp']:,.2f}",
         "delta": "change in DV01 itself for a 50bp move", "delta_color": "neutral"},
        {"label": "Fixed Leg Macaulay Duration", "value": f"{extended['fixed_leg_macaulay_duration_years']:.2f}y",
         "delta": "PV-weighted average time, fixed leg only", "delta_color": "neutral"},
    ])
    st.caption(
        "Modified/Macaulay duration for the NET swap is intentionally not shown here: a swap's NPV "
        "can sit at or near zero (e.g. priced at its own fair rate), which makes a price-weighted "
        "'% price change' duration measure blow up or become undefined -- the same divide-by-near-"
        "zero problem documented for convexity below. Macaulay duration is well-defined for the "
        "fixed leg alone (a straightforward positive cashflow stream), which is what's shown above."
    )

with tab_leg:
    kpi.render_kpi_row([
        {"label": "Fixed Leg DV01", "value": f"${extended['fixed_leg_dv01']:,.2f}"},
        {"label": "Floating Leg DV01", "value": f"${extended['floating_leg_dv01']:,.2f}"},
        {"label": "Net Swap DV01", "value": f"${risk.dv01:,.2f}",
         "delta": "floating − fixed (pay-fixed) or fixed − floating (receive-fixed)",
         "delta_color": "neutral"},
    ])
    st.caption(
        "Splits out where a swap's rate sensitivity actually lives. The floating leg's DV01 comes "
        "from the single-curve telescoping identity; the fixed leg's from its own annuity. The two "
        "partially offset (in a pay-fixed swap, the fixed leg's DV01 has the opposite sign to the "
        "net swap's), which is why a deep-in-the-money swap's net DV01 can look small even when "
        "both legs individually carry large risk."
    )

with tab_heatmap:
    st.caption(
        "Key-rate DV01 for a range of swap tenors, all struck today at this swap's own notional, "
        "fixed rate, and direction -- shows where risk concentrates on the curve as maturity "
        "changes (e.g. a 1Y swap's risk sits almost entirely in the 2Y bucket; a 30Y swap's risk "
        "concentrates in the 30Y bucket)."
    )
    heatmap_data = data_access.get_krd_heatmap_data(curve, swap.notional, swap.fixed_rate, swap.pay_fixed)
    st.plotly_chart(charts.plot_krd_heatmap(heatmap_data), use_container_width=True, config=charts.PLOTLY_CONFIG)

with st.expander("What is convexity, and why does it matter?"):
    st.markdown(
        """
DV01 is a **first-order (linear)** approximation of a nonlinear price/rate relationship.
Convexity captures the **curvature** -- how much DV01 itself changes as rates move.

It matters because a hedge sized on DV01 alone is well-hedged for a 1bp move but increasingly
mis-hedged for larger moves. Desks with large convexity exposure re-hedge more frequently
("gamma trading"), and convexity carries its own P&L in volatile markets.

This platform computes convexity via a central second difference on the fully repriced swap:

`convexity = NPV(+1bp) + NPV(-1bp) - 2 * NPV(base)`

reported in **unnormalized dollar terms** (rather than divided by price, the textbook bond
formula) because a swap's NPV can sit at or near zero -- e.g. when priced at its own fair rate --
which would make a price-normalized convexity blow up or be undefined.
"""
    )

with st.expander("Why does a pay-fixed swap have negative duration?"):
    st.markdown(
        """
Under this platform's sign convention, DV01 = NPV(curve +1bp) - NPV(curve). A **pay-fixed**
swap gains value when rates rise (you're locked into paying a below-market fixed rate), so its
DV01 is **positive**. A **receive-fixed** swap's DV01 is **negative** by the same convention --
it behaves like a long bond (gains when rates fall).

On the standard bond convention (duration = "how much you lose when yields rise"), a payer swap
therefore has *negative* duration: it is economically **short a bond** (short duration, long
floating-rate cash), while a receiver swap is economically **long a bond**.
"""
    )
