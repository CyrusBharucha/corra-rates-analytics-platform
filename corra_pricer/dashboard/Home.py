import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    # Streamlit sets sys.path[0] to this script's own directory, not the
    # project root, so `corra_pricer.*` imports fail unless we fix that up
    # first - before any corra_pricer import can happen.
    for parent in Path(__file__).resolve().parents:
        if (parent / "corra_pricer").is_dir() and (parent / "requirements.txt").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Could not locate the project root (expected a 'corra_pricer' package "
                        "and requirements.txt in a parent directory).")


_ensure_project_root_on_path()

import datetime as dt

import streamlit as st

from corra_pricer.dashboard.components import charts, data_access, styling

styling.apply_page_config("Home")

# Build the dateline without %-d/%#d (platform-specific) so it renders the
# same on Windows and Linux (Streamlit Cloud).
_d = dt.date.today()
_today = f"{_d.strftime('%A, %B')} {_d.day}, {_d.year}"

st.markdown(
    f"""<div class="masthead">
        <div class="edition">
            <span>Canadian Rates Desk &middot; <span class="place">Toronto</span></span>
            <span>{_today}</span>
        </div>
        <h1>The CORRA Desk</h1>
        <div class="standfirst">A pricing and risk analytics terminal for Canadian CORRA overnight
        indexed swaps.</div>
        <div class="byline">
            <span>Designed &amp; Developed by <b>Cyrus Bharucha</b> &middot; University of Waterloo / Wilfrid Laurier University</span>
            <span class="byline-links">
                <a href="https://www.linkedin.com/in/cyrus-bharucha" target="_blank" rel="noopener">LinkedIn</a>
                <a href="https://github.com/CyrusBharucha/corra-rates-analytics-platform" target="_blank" rel="noopener">GitHub repository</a>
            </span>
        </div>
    </div>""",
    unsafe_allow_html=True,
)

st.markdown(
    """<div class="editors-note">
        Interest rate swaps are among the most widely used instruments for managing interest-rate
        exposure. The platform demonstrates the complete workflow for pricing and risk managing Canadian CORRA
        overnight indexed swaps, from market data and curve construction through valuation, risk,
        stress testing, and historical replay, with a pricing engine implemented entirely in
        Python. Every calculation on this platform traces back to documented pricing and risk methodologies in the repository.
    </div>""",
    unsafe_allow_html=True,
)

try:
    snapshot = data_access.get_market_snapshot()
    tape_pairs = [
        ("CORRA", snapshot["corra_rate_pct"]),
        ("2Y GoC", snapshot["benchmark_yields_pct"]["2Y"]),
        ("5Y GoC", snapshot["benchmark_yields_pct"]["5Y"]),
        ("10Y GoC", snapshot["benchmark_yields_pct"]["10Y"]),
        ("30Y GoC", snapshot["benchmark_yields_pct"]["LONG"]),
    ]
    tape_items = "".join(
        f'<div class="tape-item"><div class="tape-key">{k}</div>'
        f'<div class="tape-val">{v:.2f}%</div></div>'
        for k, v in tape_pairs
    )
    st.markdown(f'<div class="tape">{tape_items}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="tape-line"><span class="tape-dot"></span> Live &middot; '
        f'Bank of Canada Valet API &middot; as of {snapshot["as_of_yields"].date()}</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="kicker" style="margin-bottom: 14px;">Current GoC-Proxy OIS Zero Curve</div>', unsafe_allow_html=True)
    curve = data_access.get_current_curve(interpolation="linear")
    st.plotly_chart(charts.plot_yield_curve(curve, label="GoC-Proxy OIS Zero Curve"),
                     use_container_width=True, config=charts.PLOTLY_CONFIG)
except Exception as exc:
    st.warning(f"Could not reach the Bank of Canada Valet API right now: {exc}")

styling.render_section_label("Where to go next")
nav_items = [
    ("pages/1_Market.py", "Market",
     "Live CORRA fixing, the GoC benchmark curve, and the bootstrapped discounting curve."),
    ("pages/2_Pricing.py", "Pricing",
     "Fair rate, NPV and the full cashflow schedule for a vanilla CORRA OIS."),
    ("pages/3_Risk.py", "Risk",
     "DV01, PV01, key-rate DV01, duration and convexity, all bump-and-reprice."),
    ("pages/4_Scenarios.py", "Scenarios",
     "41 named shocks, user-defined key-rate shocks, and Monte Carlo stress testing."),
    ("pages/5_Historical_Replay.py", "Historical Replay",
     "Re-price the same swap across the 2020-25 cycle on real Bank of Canada data."),
    ("pages/6_Documentation.py", "Documentation",
     "Architecture, methodology, and every simplification stated plainly."),
]
cols = st.columns(len(nav_items))
for col, (page, title, desc) in zip(cols, nav_items):
    with col:
        st.markdown(
            f"""<div class="nav-card"><div class="nav-title">{title}</div>
                <div class="nav-desc">{desc}</div></div>""",
            unsafe_allow_html=True,
        )
        st.page_link(page, label=f"Open {title} →", use_container_width=True)

styling.render_section_label("How the platform works")
st.markdown(
    """<div class="methodology">
        <p>Market data comes from the Bank of Canada&rsquo;s Valet API. The discounting curve is
        bootstrapped by root-finding each benchmark bond back to par, with no closed-form
        shortcut, no third-party pricing library. Swaps are valued off that curve, with the
        floating leg collapsing to a telescoping discount-factor identity that holds exactly under
        single-curve discounting.</p>
        <p>Risk is measured by bump-and-reprice rather than analytic derivatives, so every DV01,
        key-rate DV01 and convexity figure can be reproduced by shocking the curve and revaluing.
        The full stack is covered by 270 automated tests.</p>
        <p><strong>Note:</strong> Live CORRA OIS quotes are proprietary and therefore unavailable publicly. The platform bootstraps an OIS proxy curve from published Government of Canada benchmark yields.</p>
    </div>""",
    unsafe_allow_html=True,
)
