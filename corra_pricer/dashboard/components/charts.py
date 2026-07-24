"""Plotly chart builders. All computation happens in the backend; this file
only reads and reshapes already-computed objects for display."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

_TEMPLATE = "plotly_white"
_ACCENT = "#1E5B3B"
_POSITIVE = "#1E5B3B"
_NEGATIVE = "#8A2E2E"
_PALETTE = ["#1E5B3B", "#8A2E2E", "#8A6C25", "#3D6B8A", "#6B4E7A", "#A85A2E"]
_FONT = dict(family="IBM Plex Sans, sans-serif", size=13, color="#17211B")


def _base_layout(fig: go.Figure, title: str, yaxis_title: str | None = "", xaxis_title: str = "",
                  height: int = 520) -> go.Figure:
    layout_kwargs = dict(
        template=_TEMPLATE,
        title=dict(text=title, font=dict(size=15, family="Inter, sans-serif"), y=0.97, yanchor="top"),
        xaxis_title=xaxis_title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=50, r=30, t=60, b=85),
        legend=dict(orientation="h", yanchor="top", y=-0.22, xanchor="left", x=0),
        height=height,
        font=_FONT,
        hoverlabel=dict(bgcolor="#F5F7F1", bordercolor="rgba(19,30,23,0.25)",
                        font=dict(family="IBM Plex Sans, sans-serif", size=12, color="#17211B")),
        hovermode="x unified",
    )
    if yaxis_title is not None:
        layout_kwargs["yaxis_title"] = yaxis_title
    fig.update_layout(**layout_kwargs)
    fig.update_xaxes(gridcolor="rgba(19,30,23,0.12)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(19,30,23,0.12)", zeroline=False)
    # Pad trace names so horizontal legend entries don't crowd each other.
    for trace in fig.data:
        if trace.showlegend is not False and trace.name:
            trace.name = f"{trace.name}   "
    return fig


PLOTLY_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def plot_yield_curve(curve, label: str = "Curve", max_years: float = 30.0) -> go.Figure:
    smooth_t = np.linspace(0.1, max_years, 200)
    smooth_z = [curve.zero_rate(t) * 100 for t in smooth_t]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=smooth_t, y=smooth_z, mode="lines", name=label,
        line=dict(color=_ACCENT, width=3.8, shape="spline"),
        hovertemplate="%{x:.1f}Y &nbsp;→&nbsp; %{y:.3f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=curve.times, y=curve.zero_rates * 100, mode="markers", name="Bootstrap nodes",
        marker=dict(color=_ACCENT, size=12, symbol="diamond", line=dict(color="#ECEFE8", width=1.5)),
        hovertemplate="Node: %{x:.2f}Y &nbsp;→&nbsp; %{y:.3f}%<extra></extra>",
    ))
    return _base_layout(fig, f"Bootstrapped GoC-Proxy OIS Zero Curve ({curve.interpolation})",
                         "Zero Rate (%)", "Tenor (years)", height=560)


def plot_curve_comparison(curves: dict, max_years: float = 30.0,
                          title: str = "Curve Evolution") -> go.Figure:
    """curves: {label: YieldCurve or ShockedCurve}. Node markers only drawn
    for plain YieldCurve (exposes .times/.zero_rates); shocked curves are
    smooth lines only."""
    fig = go.Figure()
    smooth_t = np.linspace(0.1, max_years, 200)
    for i, (label, curve) in enumerate(curves.items()):
        color = _PALETTE[i % len(_PALETTE)]
        smooth_z = [curve.zero_rate(t) * 100 for t in smooth_t]
        fig.add_trace(go.Scatter(
            x=smooth_t, y=smooth_z, mode="lines", name=str(label),
            line=dict(color=color, width=3, shape="spline"),
            hovertemplate=f"{label}: " + "%{x:.1f}Y → %{y:.3f}%<extra></extra>",
        ))
        if hasattr(curve, "times") and hasattr(curve, "zero_rates"):
            fig.add_trace(go.Scatter(
                x=curve.times, y=curve.zero_rates * 100, mode="markers", showlegend=False,
                marker=dict(color=color, size=7, symbol="diamond", line=dict(color="#ECEFE8", width=1)),
                hoverinfo="skip",
            ))
    return _base_layout(fig, title, "Zero Rate (%)", "Tenor (years)", height=560)


def plot_krd_bar(risk_report) -> go.Figure:
    buckets = list(risk_report.krd.keys())
    values = list(risk_report.krd.values())
    colors = [_POSITIVE if v >= 0 else _NEGATIVE for v in values]
    fig = go.Figure(go.Bar(
        x=buckets, y=values, marker_color=colors, marker_line_width=0,
        text=[f"${v:,.0f}" for v in values], textposition="outside",
        hovertemplate="%{x} bucket: $%{y:,.2f}/bp<extra></extra>",
    ))
    return _base_layout(fig, "Key-Rate DV01 by Bucket", "DV01 ($/bp)", "")


def plot_krd_waterfall(risk_report) -> go.Figure:
    buckets = list(risk_report.krd.keys())
    values = list(risk_report.krd.values())
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["relative"] * len(buckets) + ["total"],
        x=buckets + ["Total DV01"],
        y=values + [0],
        text=[f"${v:,.0f}" for v in values] + [f"${risk_report.dv01:,.0f}"],
        textposition="outside",
        connector=dict(line=dict(color="rgba(19,30,23,0.25)")),
        increasing=dict(marker=dict(color=_POSITIVE)),
        decreasing=dict(marker=dict(color=_NEGATIVE)),
        totals=dict(marker=dict(color=_ACCENT)),
        hovertemplate="%{x}: $%{y:,.2f}<extra></extra>",
    ))
    return _base_layout(fig, "Key-Rate DV01 Contribution to Total", "DV01 ($/bp)", "")


def plot_scenario_grid(scenario_df, labeller=None) -> go.Figure:
    """`labeller` maps a scenario key to its display name (injected by the page
    so this module stays presentation-only and doesn't import the catalog)."""
    category_colors = {"parallel": _ACCENT, "curve_trade": "#BE9A57", "macro": "#9784B0"}
    colors = [category_colors.get(c, _ACCENT) for c in scenario_df["category"]]
    labeller = labeller or (lambda s: s.replace("_", " "))
    labels = [labeller(s) for s in scenario_df["scenario"]]
    fig = go.Figure(go.Bar(
        x=labels, y=scenario_df["npv_change"], marker_color=colors, marker_line_width=0,
        hovertemplate="%{x}<br>NPV change: $%{y:,.0f}<extra></extra>",
    ))
    fig = _base_layout(fig, "Scenario P&L  (blue = parallel · yellow = curve trade · purple = macro)",
                        "NPV Change ($)", "", height=600)
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=10))
    fig.update_layout(margin=dict(l=50, r=30, t=55, b=150))
    return fig


def plot_scenario_waterfall(scenario_result) -> go.Figure:
    """Bucket-by-bucket linear attribution, reconciled by the convexity
    residual, to the actual fully-repriced NPV change."""
    buckets = list(scenario_result.pnl_attribution_bp.keys())
    values = list(scenario_result.pnl_attribution_bp.values())
    labels = buckets + ["Convexity residual", "Actual NPV Change"]
    measures = ["relative"] * len(buckets) + ["relative", "total"]
    ys = values + [scenario_result.attribution_residual, 0]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures, x=labels, y=ys,
        text=[f"${v:,.0f}" for v in values] +
             [f"${scenario_result.attribution_residual:,.0f}", f"${scenario_result.npv_change:,.0f}"],
        textposition="outside",
        connector=dict(line=dict(color="rgba(19,30,23,0.25)")),
        increasing=dict(marker=dict(color=_POSITIVE)),
        decreasing=dict(marker=dict(color=_NEGATIVE)),
        totals=dict(marker=dict(color=_ACCENT)),
        hovertemplate="%{x}: $%{y:,.2f}<extra></extra>",
    ))
    return _base_layout(fig, "P&L Attribution: Key-Rate Buckets + Convexity Residual = Full Reprice",
                         "$ P&L", "", height=560)


def plot_npv_dv01_comparison(comparison_df) -> go.Figure:
    """DV01 bar chart across historical dates. NPV is omitted because when
    struck at fair rate it is always $0, showing it would just be noise."""
    fig = go.Figure(go.Bar(
        x=comparison_df["label"], y=comparison_df["dv01"], name="DV01 ($/bp)",
        marker_color="#BE9A57", marker_line_width=0,
        hovertemplate="%{x}<br>DV01: $%{y:,.2f}/bp<extra></extra>",
        text=[f"${v:,.0f}" for v in comparison_df["dv01"]], textposition="outside",
    ))
    fig.update_layout(hovermode="x")
    return _base_layout(fig, "DV01 by Date", "DV01 ($/bp)", "")


def plot_discount_factor_curve(curve, max_years: float = 30.0) -> go.Figure:
    smooth_t = np.linspace(0.0, max_years, 200)
    smooth_df = [curve.discount_factor(t) for t in smooth_t]
    fig = go.Figure(go.Scatter(
        x=smooth_t, y=smooth_df, mode="lines", name="Discount Factor",
        line=dict(color=_POSITIVE, width=3, shape="spline"),
        fill="tozeroy", fillcolor="rgba(30,91,59,0.09)",
        hovertemplate="%{x:.1f}Y &nbsp;→&nbsp; DF %{y:.6f}<extra></extra>",
    ))
    return _base_layout(fig, "Discount Factor Curve", "Discount Factor", "Tenor (years)")


def plot_forward_curve(curve, max_years: float = 29.75, window: float = 0.25) -> go.Figure:
    starts = np.linspace(0.1, max_years, 200)
    fwd = [curve.forward_rate(t, t + window) * 100 for t in starts]
    fig = go.Figure(go.Scatter(
        x=starts, y=fwd, mode="lines", name=f"{int(window*12)}M forward rate",
        line=dict(color="#9784B0", width=2.5, shape="spline"),
        hovertemplate="Start %{x:.1f}Y &nbsp;→&nbsp; %{y:.3f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=curve.times, y=curve.zero_rates * 100, mode="lines", name="Zero Curve (reference)",
        line=dict(color=_ACCENT, width=1.5, dash="dot"),
        hovertemplate="%{x:.1f}Y zero &nbsp;→&nbsp; %{y:.3f}%<extra></extra>",
    ))
    return _base_layout(fig, f"Implied {int(window*12)}-Month Forward Rate Curve",
                         "Forward Rate (%)", "Start of forward period (years)")


def plot_bootstrap_residuals(residuals: dict) -> go.Figure:
    """residuals: {tenor: price - 100}. Near-zero bars confirm the bootstrap
    converged; any large bar means a par bond doesn't reprice to par."""
    _TENOR_LABELS = {"LONG": "30Y"}
    tenors = [_TENOR_LABELS.get(t, t) for t in residuals.keys()]
    values = list(residuals.values())
    colors = [_POSITIVE if abs(v) < 0.05 else ("#BE9A57" if abs(v) < 0.5 else _NEGATIVE) for v in values]
    labels = ["≈ 0" if abs(v) < 1e-4 else f"{v:+.4f}" for v in values]
    fig = go.Figure(go.Bar(
        x=tenors, y=values, marker_color=colors, marker_line_width=0,
        text=labels, textposition="outside",
        hovertemplate="%{x}: reprice error %{y:.2e} per $100 face<extra></extra>",
    ))
    fig.add_hline(y=0, line_color="rgba(19,30,23,0.32)")
    _base_layout(fig, "Bootstrap Diagnostic: Par Bond Repricing Error",
                 "Price − 100 (per $100 face)", "", height=520)
    fig.update_yaxes(range=[-1, 1], tickformat=".2f")
    return fig


def plot_interpolation_divergence(curves: dict, reference: str = "linear", max_years: float = 30.0,
                                   labels: dict | None = None) -> go.Figure:
    """curves: {method_name: YieldCurve}. Each non-reference curve is plotted
    as (zero_rate - reference_zero_rate) in bp, showing where interpolation
    choice actually affects pricing."""
    labels = labels or {}
    smooth_t = np.linspace(0.1, max_years, 200)
    ref_curve = curves[reference]
    ref_z = np.array([ref_curve.zero_rate(t) for t in smooth_t])
    fig = go.Figure()
    for i, (method, curve) in enumerate(curves.items()):
        if method == reference:
            continue
        color = _PALETTE[i % len(_PALETTE)]
        z = np.array([curve.zero_rate(t) for t in smooth_t])
        diff_bp = (z - ref_z) * 10_000
        fig.add_trace(go.Scatter(
            x=smooth_t, y=diff_bp, mode="lines", name=f"{labels.get(method, method)} − {labels.get(reference, reference)}",
            line=dict(color=color, width=2.5),
            hovertemplate="%{x:.1f}Y: %{y:+.2f}bp<extra></extra>",
        ))
    fig.add_hline(y=0, line_color="rgba(19,30,23,0.32)")
    return _base_layout(fig, f"Interpolation Method Divergence (vs. {labels.get(reference, reference)})",
                         "Difference (bp)", "Tenor (years)", height=520)


def plot_krd_heatmap(heatmap_data: dict, title: str = "Key-Rate DV01 Heatmap Across Swap Tenors",
                      row_label: str = "Swap Tenor", row_hover_label: str = "Swap tenor") -> go.Figure:
    """heatmap_data: {row_label: {bucket_label: krd_value}}. Works for both
    swap-tenor rows (Risk page) and historical-date rows (Historical Replay)."""
    rows = list(heatmap_data.keys())
    buckets = list(next(iter(heatmap_data.values())).keys())
    z = [[heatmap_data[r][b] for b in buckets] for r in rows]
    fig = go.Figure(go.Heatmap(
        z=z, x=buckets, y=rows, colorscale="RdBu", zmid=0,
        hovertemplate=f"{row_hover_label} " + "%{y}, bucket %{x}: $%{z:,.0f}/bp<extra></extra>",
        colorbar=dict(title="DV01 ($/bp)"),
    ))
    return _base_layout(fig, title, row_label, "Curve Bucket", height=540)


def plot_monte_carlo_histogram(mc_df) -> go.Figure:
    npv = mc_df["npv_change"]
    fig = go.Figure(go.Histogram(
        x=npv, nbinsx=40, marker_color=_ACCENT, opacity=0.85,
        hovertemplate="P&L range: %{x}<br>Count: %{y}<extra></extra>",
    ))
    mean_val = npv.mean()
    fig.add_vline(x=mean_val, line_color=_POSITIVE, line_dash="dash",
                  annotation_text=f"Mean: ${mean_val:,.0f}", annotation_position="top")
    p5, p95 = npv.quantile(0.05), npv.quantile(0.95)
    fig.add_vline(x=p5, line_color=_NEGATIVE, line_dash="dot", annotation_text="5th pct")
    fig.add_vline(x=p95, line_color=_NEGATIVE, line_dash="dot", annotation_text="95th pct")
    return _base_layout(fig, f"Monte Carlo P&L Distribution ({len(mc_df)} simulations)",
                         "Count", "NPV Change ($)", height=520)


def plot_curve_animation(curves: dict, max_years: float = 30.0) -> go.Figure:
    """curves: {label: YieldCurve}, in chronological order. One Plotly frame
    per date with a slider and play/pause controls."""
    smooth_t = np.linspace(0.1, max_years, 150)
    labels = list(curves.keys())

    first_curve = curves[labels[0]]
    fig = go.Figure(
        data=[go.Scatter(
            x=smooth_t, y=[first_curve.zero_rate(t) * 100 for t in smooth_t],
            mode="lines", line=dict(color=_ACCENT, width=3, shape="spline"),
            hovertemplate="%{x:.1f}Y &nbsp;→&nbsp; %{y:.3f}%<extra></extra>",
        )],
        frames=[
            go.Frame(
                name=label,
                data=[go.Scatter(x=smooth_t, y=[curves[label].zero_rate(t) * 100 for t in smooth_t])],
            )
            for label in labels
        ],
    )

    all_rates = [curves[label].zero_rate(t) * 100 for label in labels for t in smooth_t]
    y_range = [min(all_rates) - 0.3, max(all_rates) + 0.3]

    fig.update_layout(
        sliders=[{
            "active": 0,
            "steps": [
                {"label": label, "method": "animate",
                 "args": [[label], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}]}
                for label in labels
            ],
            "x": 0.05, "len": 0.9,
        }],
        updatemenus=[{
            "type": "buttons",
            "buttons": [
                {"label": "Play", "method": "animate",
                 "args": [None, {"frame": {"duration": 700, "redraw": True}, "fromcurrent": True}]},
                {"label": "Pause", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}]},
            ],
            "x": 0.0, "y": 1.12, "xanchor": "left",
        }],
        yaxis=dict(range=y_range),
    )
    return _base_layout(fig, "Yield Curve Evolution Through Time", "Zero Rate (%)", "Tenor (years)", height=580)


def plot_metric_timeline(comparison_df) -> go.Figure:
    """Dual-axis fair rate and DV01 time series across historical dates."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=comparison_df["label"], y=comparison_df["fair_rate_pct"], name="Fair Rate (%)",
        mode="lines+markers", line=dict(color=_ACCENT, width=2.5), yaxis="y1",
        hovertemplate="%{x}<br>Fair rate: %{y:.3f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=comparison_df["label"], y=comparison_df["dv01"], name="DV01 ($/bp)",
        mode="lines+markers", line=dict(color="#BE9A57", width=2.5), yaxis="y2",
        hovertemplate="%{x}<br>DV01: $%{y:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        yaxis=dict(title="Fair Rate (%)", gridcolor="rgba(19,30,23,0.12)"),
        yaxis2=dict(title="DV01 ($/bp)", overlaying="y", side="right", gridcolor="rgba(0,0,0,0)"),
    )
    return _base_layout(fig, "Fair Rate and DV01 Through Time", yaxis_title=None, height=520)
