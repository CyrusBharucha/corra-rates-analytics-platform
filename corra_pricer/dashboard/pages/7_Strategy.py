"""
Moving Average Crossover Strategy on CORRA.

Strategy Logic (dead simple to present):
  - 5-day MA crosses ABOVE 20-day MA → rates are rising → Pay Fixed (short duration)
  - 5-day MA crosses BELOW 20-day MA → rates are falling → Receive Fixed (long duration)

This page fetches the full CORRA daily history from BoC, runs the signal,
shows the trade log, and reports Sharpe ratio + win rate.
"""
import sys
from pathlib import Path


def _ensure_project_root_on_path() -> None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "corra_pricer").is_dir() and (parent / "requirements.txt").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Could not locate project root.")


_ensure_project_root_on_path()

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from corra_pricer.dashboard.components import kpi, styling
from corra_pricer.market_data.boc_valet_client import fetch_corra_history

# ── Page chrome ──────────────────────────────────────────────────────────────
styling.apply_page_config("Strategy")
styling.render_header(
    "MA Crossover Strategy",
    "Moving-average signal on CORRA overnight fixing — pay/receive fixed on OIS",
)

# ── Strategy explainer ────────────────────────────────────────────────────────
st.markdown(
    """
<div class="editors-note">
<b>The Strategy in one sentence:</b> When short-term CORRA momentum turns up, rates are
rising — we <em>pay fixed</em> on a CORRA OIS (profit from higher floating leg). When momentum
turns down, we <em>receive fixed</em> (profit from lower floating leg).<br><br>
<b>Signal:</b> 5-day moving average crosses the 20-day moving average of the daily CORRA fixing.<br>
<b>Position:</b> &nbsp;+1 = Pay Fixed &nbsp;|&nbsp; −1 = Receive Fixed<br>
<b>P&amp;L proxy:</b> daily change in CORRA × position (in basis points).
</div>
""",
    unsafe_allow_html=True,
)

# ── Sidebar controls ──────────────────────────────────────────────────────────
st.sidebar.markdown("### Strategy Parameters")
fast_window = st.sidebar.slider("Fast MA (days)", min_value=3, max_value=20, value=5, step=1)
slow_window = st.sidebar.slider("Slow MA (days)", min_value=10, max_value=60, value=20, step=1)
start_year = st.sidebar.slider("Backtest start year", min_value=2019, max_value=2023, value=2020)

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_corra_history(start: dt.date) -> pd.DataFrame:
    return fetch_corra_history(start_date=start)


with st.spinner("Fetching CORRA history from Bank of Canada…"):
    try:
        df = load_corra_history(dt.date(start_year, 1, 1))
    except Exception as exc:
        st.error(f"Failed to load CORRA history: {exc}")
        st.stop()

if df.empty or len(df) < slow_window + 5:
    st.warning("Not enough data to run the strategy. Try an earlier start year.")
    st.stop()

# ── Signal construction ───────────────────────────────────────────────────────
df = df.copy().sort_values("date").reset_index(drop=True)
df["fast_ma"] = df["corra"].rolling(fast_window).mean()
df["slow_ma"] = df["corra"].rolling(slow_window).mean()

# Position: +1 (pay fixed) when fast > slow, -1 (receive fixed) otherwise.
# Shift by 1 so we trade on tomorrow's open, not today's close (no look-ahead).
df["raw_signal"] = np.where(df["fast_ma"] > df["slow_ma"], 1.0, -1.0)
df["position"] = df["raw_signal"].shift(1)

# Daily CORRA change (in bp)
df["corra_chg_bp"] = df["corra"].diff() * 100  # pct → bp

# Daily P&L (bp): position × daily rate change
# Pay Fixed profits when rates rise; Receive Fixed profits when rates fall.
df["pnl_bp"] = df["position"] * df["corra_chg_bp"]

# Drop warm-up rows
df_bt = df.dropna(subset=["position", "pnl_bp"]).copy()
df_bt["cum_pnl_bp"] = df_bt["pnl_bp"].cumsum()

# Crossover events (signal flips)
df_bt["prev_signal"] = df_bt["raw_signal"].shift(1)
crossovers = df_bt[df_bt["raw_signal"] != df_bt["prev_signal"]].copy()

# ── Performance stats ─────────────────────────────────────────────────────────
n_days = len(df_bt)
n_trades = len(crossovers)
win_rate = (df_bt["pnl_bp"] > 0).mean() * 100
total_pnl = df_bt["pnl_bp"].sum()
daily_mean = df_bt["pnl_bp"].mean()
daily_std = df_bt["pnl_bp"].std()
sharpe = (daily_mean / daily_std * np.sqrt(252)) if daily_std > 0 else 0.0

# Max drawdown
rolling_max = df_bt["cum_pnl_bp"].cummax()
drawdown = df_bt["cum_pnl_bp"] - rolling_max
max_drawdown = drawdown.min()

# ── KPI row ───────────────────────────────────────────────────────────────────
kpi.render_kpi_row([
    {"label": "Total P&L", "value": f"{total_pnl:+.1f} bp",
     "delta": "cumulative carry since backtest start",
     "delta_color": "positive" if total_pnl >= 0 else "negative"},
    {"label": "Sharpe Ratio", "value": f"{sharpe:.2f}",
     "delta": "annualised (√252 scaling)",
     "delta_color": "positive" if sharpe >= 1 else "negative" if sharpe < 0 else "neutral"},
    {"label": "Win Rate", "value": f"{win_rate:.1f}%",
     "delta": f"of {n_days:,} trading days",
     "delta_color": "positive" if win_rate >= 50 else "negative"},
    {"label": "Max Drawdown", "value": f"{max_drawdown:.1f} bp",
     "delta": f"peak-to-trough · {n_trades} signal flips",
     "delta_color": "negative"},
])

# ── Chart helpers ─────────────────────────────────────────────────────────────
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

ACCENT = "#1E5B3B"
GOLD = "#8A6C25"
NEG = "#8A2E2E"
MUTED = "#56604F"
BG = "#F5F7F1"
PAPER = "#ECEFE8"
BORDER = "rgba(19,30,23,0.14)"

LAYOUT_BASE = dict(
    paper_bgcolor=PAPER,
    plot_bgcolor=BG,
    font=dict(family="IBM Plex Sans, -apple-system, sans-serif", color="#17211B", size=12),
    margin=dict(l=0, r=0, t=36, b=0),
    xaxis=dict(showgrid=False, zeroline=False, linecolor=BORDER, tickfont=dict(size=11)),
    yaxis=dict(showgrid=True, gridcolor=BORDER, zeroline=True,
               zerolinecolor=BORDER, linecolor=BORDER, tickfont=dict(size=11)),
    legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0, font=dict(size=11)),
    hovermode="x unified",
)

# ── Tab 1: CORRA + Moving Averages + Signals ──────────────────────────────────
tab_signal, tab_pnl, tab_trades = st.tabs(["Signal", "P&L", "Trade Log"])

with tab_signal:
    styling.render_section_label("CORRA Fixing with Moving Averages")
    st.caption(
        f"Daily CORRA fixing (Bank of Canada) with {fast_window}-day and {slow_window}-day "
        f"moving averages. A **crossover up** (green ▲) triggers a pay-fixed trade; "
        f"a **crossover down** (red ▼) triggers receive-fixed."
    )

    # Build crossover markers
    bull_crosses = crossovers[crossovers["raw_signal"] == 1.0]
    bear_crosses = crossovers[crossovers["raw_signal"] == -1.0]

    fig_signal = go.Figure()
    fig_signal.add_trace(go.Scatter(
        x=df_bt["date"], y=df_bt["corra"],
        name="CORRA Fixing",
        line=dict(color=MUTED, width=1.2),
        hovertemplate="%{y:.3f}%",
    ))
    fig_signal.add_trace(go.Scatter(
        x=df_bt["date"], y=df_bt["fast_ma"],
        name=f"{fast_window}d MA (fast)",
        line=dict(color=ACCENT, width=1.8, dash="solid"),
        hovertemplate="%{y:.3f}%",
    ))
    fig_signal.add_trace(go.Scatter(
        x=df_bt["date"], y=df_bt["slow_ma"],
        name=f"{slow_window}d MA (slow)",
        line=dict(color=GOLD, width=1.8, dash="dot"),
        hovertemplate="%{y:.3f}%",
    ))
    # Buy signals
    fig_signal.add_trace(go.Scatter(
        x=bull_crosses["date"], y=bull_crosses["corra"],
        mode="markers", name="Pay Fixed ▲",
        marker=dict(symbol="triangle-up", size=10, color=ACCENT),
        hovertemplate="Pay Fixed<br>%{x|%Y-%m-%d}<br>CORRA: %{y:.3f}%",
    ))
    # Sell signals
    fig_signal.add_trace(go.Scatter(
        x=bear_crosses["date"], y=bear_crosses["corra"],
        mode="markers", name="Receive Fixed ▼",
        marker=dict(symbol="triangle-down", size=10, color=NEG),
        hovertemplate="Receive Fixed<br>%{x|%Y-%m-%d}<br>CORRA: %{y:.3f}%",
    ))
    fig_signal.update_layout(
        **LAYOUT_BASE,
        title=dict(text="CORRA Fixing & MA Crossover Signals", font=dict(
            family="Source Serif 4, Georgia, serif", size=15, color="#17211B")),
        yaxis_title="Rate (%)",
        height=420,
    )
    st.plotly_chart(fig_signal, use_container_width=True, config=PLOTLY_CONFIG)

with tab_pnl:
    styling.render_section_label("Cumulative P&L (basis points)")
    st.caption(
        "Each day, position × daily CORRA change gives the P&L in basis points. "
        "Pay Fixed profits when CORRA rises; Receive Fixed profits when CORRA falls. "
        "The shaded band shows the maximum drawdown period."
    )

    # Identify max drawdown period
    dd_end_idx = drawdown.idxmin()
    peak_before = df_bt.loc[:dd_end_idx, "cum_pnl_bp"].idxmax()
    dd_start_date = df_bt.loc[peak_before, "date"]
    dd_end_date = df_bt.loc[dd_end_idx, "date"]

    fig_pnl = go.Figure()
    # Drawdown shading
    fig_pnl.add_vrect(
        x0=dd_start_date, x1=dd_end_date,
        fillcolor=NEG, opacity=0.08, layer="below", line_width=0,
        annotation_text="Max drawdown", annotation_position="top left",
        annotation_font=dict(size=10, color=NEG),
    )
    # Zero line
    fig_pnl.add_hline(y=0, line_color=BORDER, line_width=1)
    # Cumulative P&L
    fig_pnl.add_trace(go.Scatter(
        x=df_bt["date"], y=df_bt["cum_pnl_bp"],
        name="Cumulative P&L",
        line=dict(color=ACCENT, width=2.2),
        fill="tozeroy",
        fillcolor="rgba(30,91,59,0.10)",
        hovertemplate="%{x|%Y-%m-%d}<br>Cum. P&L: %{y:+.1f} bp<extra></extra>",
    ))
    fig_pnl.update_layout(
        **LAYOUT_BASE,
        title=dict(text="Strategy Cumulative P&L", font=dict(
            family="Source Serif 4, Georgia, serif", size=15, color="#17211B")),
        yaxis_title="Cumulative P&L (bp)",
        height=420,
    )
    st.plotly_chart(fig_pnl, use_container_width=True, config=PLOTLY_CONFIG)

    # Performance summary table
    styling.render_section_label("Performance Summary")
    perf = pd.DataFrame({
        "Metric": [
            "Total P&L (bp)", "Annualised Sharpe", "Win Rate",
            "Max Drawdown (bp)", "No. of Signal Flips", "Trading Days",
        ],
        "Value": [
            f"{total_pnl:+.1f}",
            f"{sharpe:.2f}",
            f"{win_rate:.1f}%",
            f"{max_drawdown:.1f}",
            str(n_trades),
            str(n_days),
        ],
    })
    st.table(perf)

with tab_trades:
    styling.render_section_label("Signal Flip Log")
    st.caption("Every date the strategy changed direction. Green = pay fixed (long rates view); Red = receive fixed (short rates view).")

    if crossovers.empty:
        st.info("No crossovers detected in this date range.")
    else:
        display = pd.DataFrame({
            "Date": crossovers["date"].dt.strftime("%Y-%m-%d").values,
            "CORRA": crossovers["corra"].map("{:.3f}%".format).values,
            f"{fast_window}d MA": crossovers["fast_ma"].map("{:.3f}%".format).values,
            f"{slow_window}d MA": crossovers["slow_ma"].map("{:.3f}%".format).values,
            "Trade": crossovers["raw_signal"].map({1.0: "▲ Pay Fixed", -1.0: "▼ Receive Fixed"}).values,
        })
        st.dataframe(display, use_container_width=True, hide_index=True)

# ── Footer note ───────────────────────────────────────────────────────────────
st.markdown(
    """<div class="signoff">
    P&amp;L is expressed in basis points of rate change, scaled by position direction (+1/−1).
    This is a signal-only backtest; no notional, funding cost, or transaction cost is modelled.
    All data sourced from the Bank of Canada Valet API (public).
    </div>""",
    unsafe_allow_html=True,
)
