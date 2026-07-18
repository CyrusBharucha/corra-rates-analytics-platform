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
from corra_pricer.pricing_engine.conventions import year_fraction

styling.apply_page_config("Pricing")
styling.render_header("Pricing", "Price a vanilla Canadian CORRA OIS off the live curve")

curve = data_access.get_current_curve(interpolation="linear")

left, right = st.columns([1, 1.3], gap="large")

with left:
    styling.render_section_label("Trade Inputs")
    with st.container(border=True):
        trade_date = st.date_input("Trade date", value=dt.date.today())
        spot_lag_label = st.selectbox("Spot lag", ["T+0", "T+1", "T+2"], index=2,
                                       help="Business days between trade date and settlement "
                                            "(effective date), skipping weekends/holidays on the "
                                            "Canada calendar.")
        spot_lag_days = int(spot_lag_label[2:])
        spot = data_access.spot_date(trade_date, spot_lag_days, "Canada")

        start_type = st.radio("Start type", ["Spot Start", "Forward Start", "IMM Start"], horizontal=True)
        if start_type == "Spot Start":
            effective_date = spot
        elif start_type == "Forward Start":
            effective_date = st.date_input("Forward start date", value=spot + dt.timedelta(days=90),
                                            min_value=spot)
        else:
            imm = data_access.next_imm_date(spot)
            st.caption(f"Next IMM date on/after spot: **{imm.isoformat()}**")
            effective_date = imm

        tenor_label = st.selectbox("Tenor", list(data_access.TENORS_YEARS.keys()), index=3)
        freq_label = st.selectbox("Payment frequency", list(data_access.PAYMENT_FREQUENCIES.keys()), index=0)
        notional = st.number_input("Notional ($)", min_value=1_000, value=10_000_000, step=100_000)
        pay_fixed = st.radio("Direction", ["Pay Fixed", "Receive Fixed"]) == "Pay Fixed"
        price_at_fair = st.checkbox("Price at fair (par) rate", value=True)
        fixed_rate_input = st.number_input(
            "Fixed rate (%)", min_value=-5.0, max_value=25.0, value=3.00, step=0.05,
            disabled=price_at_fair,
        )

        with st.expander("Advanced Settings"):
            daycount = st.selectbox("Fixed leg day count", data_access.DAYCOUNT_CHOICES,
                                     help="ACT/365F: actual days / 365 (CORRA OIS market standard). "
                                          "ACT/360: actual days / 360 (money-market convention). "
                                          "30/360: each month counted as 30 days (bond-basis). "
                                          "ACT/ACT: actual days / actual days in each calendar year (ISDA).")
            stub = st.selectbox("Stub", data_access.STUB_CHOICES,
                                 format_func=lambda s: data_access.STUB_LABELS[s],
                                 help="Where the odd (non-whole-period) leftover sits when the tenor "
                                      "doesn't divide evenly: at the front (first) or back (last) of "
                                      "the schedule, kept short or merged into a longer neighbor.")
            bdc = st.selectbox("Business day convention", data_access.BUSINESS_DAY_CONVENTION_CHOICES,
                                help="How a payment date that lands on a weekend/holiday gets moved "
                                     "to a real business day.")
            calendar_name = st.selectbox("Calendar", data_access.CALENDAR_CHOICES,
                                          index=0 if bdc != "None" else data_access.CALENDAR_CHOICES.index("Weekend Only"))

        tenor_years = data_access.TENORS_YEARS[tenor_label]
        payments_per_year = data_access.PAYMENT_FREQUENCIES[freq_label]
        maturity_date = data_access.maturity_from_tenor(effective_date, tenor_years)
        st.caption(f"Spot date: {spot.isoformat()} &middot; Effective date: {effective_date.isoformat()} "
                   f"&middot; Maturity date: {maturity_date.isoformat()}", unsafe_allow_html=True)

placeholder_rate = 0.0 if price_at_fair else fixed_rate_input / 100.0
swap = data_access.build_swap(
    trade_date, maturity_date, notional, placeholder_rate, pay_fixed,
    payments_per_year=payments_per_year, effective_date=effective_date,
    fixed_leg_daycount=daycount, business_day_convention=bdc, calendar_name=calendar_name, stub=stub,
)
fair_rate = swap.fair_rate(curve)
swap.fixed_rate = fair_rate if price_at_fair else fixed_rate_input / 100.0
summary = data_access.price_swap(swap, curve)

with right:
    styling.render_section_label("Results")
    with st.container(border=True):
        kpi.render_kpi_row([
            {"label": "Fair Rate", "value": f"{summary['fair_rate_pct']:.4f}%",
             "help": "The fixed rate that makes NPV = 0 today -- the par/mid market rate for this swap."},
            {"label": "Fixed Rate", "value": f"{summary['fixed_rate_pct']:.4f}%"},
            {"label": "Direction", "value": "Pay Fixed" if pay_fixed else "Receive Fixed"},
        ])
        st.write("")
        npv_display = kpi.snap_zero(summary["npv"])
        kpi.render_kpi_row([
            {
                "label": "NPV", "value": kpi.money(summary["npv"]),
                "delta": "In your favour" if npv_display >= 0 else "Against your favour",
                "delta_color": "positive" if npv_display >= 0 else "negative",
                "help": "Net present value: what this swap is worth to unwind today, given the "
                        "fixed rate vs. the curve's current fair rate.",
            },
            {"label": "Fixed Leg PV", "value": f"${summary['fixed_leg_pv']:,.0f}"},
            {"label": "Floating Leg PV", "value": f"${summary['floating_leg_pv']:,.0f}"},
        ])
        st.caption(f"{summary['num_payments']} payment(s) over the life of the swap")

st.write("")
tab_summary, tab_schedule, tab_disc, tab_fwd, tab_val, tab_assump = st.tabs(
    ["Summary", "Cashflow Schedule", "Discount Curve", "Forward Curve",
     "Valuation Details", "Assumptions"]
)

with tab_summary:
    st.markdown(
        f"""**{"Pay" if pay_fixed else "Receive"} Fixed** &middot; ${notional:,.0f} notional &middot;
        {tenor_label} &middot; {freq_label} &middot; {swap.fixed_rate * 100:.4f}% fixed &middot;
        trade date {trade_date.isoformat()} &middot; effective {effective_date.isoformat()} &middot;
        matures {maturity_date.isoformat()}""",
        unsafe_allow_html=True,
    )
    st.caption(
        "NPV is the fair-value difference between the fixed rate you're paying/receiving and the "
        "curve's current fair rate, discounted back through the annuity -- it's what this swap "
        "would be worth to unwind today, not a cash payment."
    )

with tab_schedule:
    st.caption("Every fixed-leg payment period: accrual, discount factor, and PV -- the same "
               "building blocks fixed_leg_pv() sums internally, broken out row by row.")
    st.dataframe(tables.format_cashflow_schedule(swap, curve), use_container_width=True, hide_index=True)
    st.caption("Floating leg PV uses the single-curve telescoping identity "
               "(notional × [DF(start) − DF(end)]) rather than a period-by-period cashflow "
               "projection -- see the Assumptions tab.")

with tab_disc:
    st.plotly_chart(charts.plot_discount_factor_curve(curve), use_container_width=True,
                     config=charts.PLOTLY_CONFIG)

with tab_fwd:
    st.plotly_chart(charts.plot_forward_curve(curve), use_container_width=True, config=charts.PLOTLY_CONFIG)
    st.caption("The market-implied 3-month forward CORRA path -- the rate the curve says should "
               "prevail for a 3-month period starting at each point in time, derived purely from "
               "today's discount factors (no separate forecasting model).")

with tab_val:
    t_maturity = year_fraction(swap.trade_date, swap.maturity_date)
    total_df = curve.discount_factor(t_maturity)
    annuity = swap.annuity(curve)
    spread_bp = (swap.fixed_rate - fair_rate) * 10_000
    kpi.render_kpi_row([
        {"label": "Trade Date", "value": swap.trade_date.isoformat()},
        {"label": "Effective (Settlement) Date", "value": swap.effective_date.isoformat()},
        {"label": "Curve Date", "value": str(data_access.get_market_snapshot()["as_of_yields"].date())},
    ])
    st.write("")
    kpi.render_kpi_row([
        {"label": "Total Discount Factor (to maturity)", "value": f"{total_df:.6f}"},
        {"label": "Annuity Factor ($1 running coupon PV)", "value": f"{annuity:.6f}"},
        {"label": "Fixed vs. Fair Spread", "value": f"{spread_bp:+.2f} bp",
         "delta": "fixed rate minus fair rate", "delta_color": "neutral"},
    ])

with tab_assump:
    st.markdown(
        f"""
- **Fixed leg day count**: {daycount}
- **Payment frequency**: {freq_label}
- **Stub**: {data_access.STUB_LABELS[stub]}
- **Business day convention**: {bdc} &nbsp; **Calendar**: {calendar_name} (approximate, not sourced from an official Payments Canada/ECB feed)
- **Spot lag**: {spot_lag_label} &nbsp; **Start type**: {start_type}
- **Discounting curve**: bootstrapped from Bank of Canada GoC benchmark bond yields, used as an OIS proxy (live CORRA OIS swap quotes are not publicly available)
- **Floating leg**: single-curve telescoping identity, notional × (DF(start) − DF(end)) -- exact under single-curve discounting. Its day count is not separately selectable: the telescoping identity is a pure discount-factor relationship with no explicit compounding calculation to apply a convention to.
- **Discounting time-to-cashflow**: always ACT/365 Fixed (the curve's own time convention), independent of the fixed leg's accrual day count above.
- **Curve interpolation**: linear on zero rate (Market page lets you compare log-linear-DF and cubic spline)
"""
    )

# Share this exact swap + curve with the Risk and Scenarios pages.
st.session_state["priced_swap"] = swap
st.session_state["pricing_curve"] = curve
st.success("This swap is now available on the Risk and Scenarios pages.")
