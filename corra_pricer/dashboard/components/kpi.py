"""
Styled KPI card row -- replaces st.metric's default look with rounded,
bordered cards matching the platform's dark, institutional theme.
Presentation only: takes already-computed values, renders HTML.
"""
from __future__ import annotations

import streamlit as st

_COLORS = {
    "positive": "#4CD787",
    "negative": "#F0616D",
    "neutral": "#3FA9F5",
}


def snap_zero(value: float, threshold: float = 0.005) -> float:
    """Dollar amounts computed at a swap's own fair rate are mathematically
    ~0 but land on a tiny floating-point epsilon that can be negative,
    which would otherwise display as a confusing '$-0'. Snaps anything
    within threshold of zero to exactly 0.0 for display purposes only --
    never used for the underlying stored/computed value."""
    return 0.0 if abs(value) < threshold else value


def money(value: float, threshold: float = 0.005) -> str:
    """Formats a dollar KPI value, snapping near-zero epsilons to a clean $0."""
    return f"${snap_zero(value, threshold):,.0f}"


def _delta_html(delta: str | None, delta_color: str) -> str:
    if not delta:
        return ""
    color = _COLORS.get(delta_color, _COLORS["neutral"])
    return f'<div class="kpi-delta" style="color:{color}">{delta}</div>'


def render_kpi_row(cards: list[dict]) -> None:
    """cards: [{"label": str, "value": str, "delta": str|None, "delta_color": "positive"|"negative"|"neutral", "help": str|None}]"""
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            help_html = f'<div class="kpi-help" title="{card.get("help", "")}">&#9432;</div>' if card.get("help") else ""
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-label">{card['label']}{help_html}</div>
                    <div class="kpi-value">{card['value']}</div>
                    {_delta_html(card.get('delta'), card.get('delta_color', 'neutral'))}
                </div>
                """,
                unsafe_allow_html=True,
            )
