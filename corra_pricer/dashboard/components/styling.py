"""Shared page chrome: page config, a full CSS pass for an institutional
dark-terminal look, and reusable header/status components. Presentation
only -- no backend calls live here.
"""
from __future__ import annotations

import streamlit as st

APP_NAME = "CORRA Rates Analytics Platform"

_FONT_LINKS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&'
    'family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&'
    'family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">'
)

_CSS = """<style>
:root {
    /* "The Ledger": a Bank-of-Canada bond-note palette. A cool banknote-paper
       ground (faint green-grey, not warm cream), deep green-black ink, an
       engraved bottle-green accent, and a muted ochre for editorial marks --
       reads like a printed rates note, not a dark dashboard template. */
    --bg-page: #ECEFE8;
    --bg-card: #F5F7F1;
    --bg-card-hover: #EAEEE3;
    --border-subtle: rgba(19,30,23,0.14);
    --text-primary: #17211B;
    --text-muted: #56604F;
    --accent: #1E5B3B;
    --gold: #8A6C25;
    --positive: #1E5B3B;
    --negative: #8A2E2E;
    --font-sans: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-serif: 'Source Serif 4', Georgia, 'Times New Roman', serif;
    --font-mono: 'IBM Plex Mono', 'Consolas', monospace;
}

html, body, [class*="css"] {
    font-family: var(--font-sans);
}

.stApp {
    background: var(--bg-page);
}

/* Streamlit locks body text to a cool grey (#31333F). Force the Ledger's
   green-black ink at the root so headings (which inherit) pick it up too.
   Component classes that set their own explicit colour (muted labels, accents)
   keep it -- an element's own declaration always beats an inherited one, so
   this only recolours text that would otherwise fall through to the default. */
html, body, .stApp,
[data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stMarkdownContainer"] {
    color: var(--text-primary) !important;
}

/* Strip default Streamlit chrome -- menu, footer, deploy button. */
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }

/* Streamlit's built-in accent is a bright red (#FF4B4B). Recolour the visible
   accent surfaces to the Ledger's bottle-green so nothing clashes -- tabs,
   links, the active sidebar page, and selected controls. (The theme config
   also sets this, but overriding here guarantees it regardless of whether the
   host reads .streamlit/config.toml.) */
[data-baseweb="tab-highlight"],
.react-aria-SelectionIndicator,
.react-aria-SelectionIndicator > div,
[role="tablist"] [aria-selected="true"] > div:last-child { background-color: var(--accent) !important; }
/* Native inputs ship with the browser's default mid-grey border, which reads as
   unstyled against the paper ground. Give every control the same hairline as
   the cards, and a bottle-green ring on focus instead of the default outline. */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="select"] > div,
[data-testid="stNumberInput"] > div, [data-testid="stTextInput"] > div > div,
[data-testid="stSelectbox"] > div > div, [data-testid="stMultiSelect"] > div > div,
[data-testid="stDateInput"] > div > div {
    border-color: var(--border-subtle) !important;
    background-color: var(--bg-card) !important;
}
[data-testid="stTextInput"] input:focus, [data-testid="stNumberInput"] input:focus,
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 2px rgba(30,91,59,0.18) !important;
}
[role="tab"][aria-selected="true"],
[role="tab"][aria-selected="true"] *,
[data-testid="stTab"][aria-selected="true"],
[data-testid="stTab"][aria-selected="true"] * { color: var(--accent) !important; }
.stApp a, [data-testid="stMarkdownContainer"] a { color: var(--accent); }
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNav"] a[aria-current="page"] * { color: var(--accent) !important; font-weight: 600; }
[data-baseweb="checkbox"] input:checked + div,
[data-baseweb="radio"] div[data-checked="true"] { background-color: var(--accent) !important; border-color: var(--accent) !important; }
[data-testid="stSlider"] [role="slider"] { background-color: var(--accent) !important; }

/* Remove the sidebar collapse arrow so the left nav can never be hidden.
   Streamlit persists the collapsed state per-origin in localStorage and its
   own re-expand control is unreliable, so the only durable fix is to not
   offer collapsing at all. This only hides the control; the sidebar itself
   renders normally (verified against a fresh, cleared-storage session). */
[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* Streamlit's header/sidebar icon buttons (collapse/expand sidebar, main
   menu) render in its light-theme default color (near-black), which is
   invisible against this app's dark background -- most visibly the
   sidebar's re-expand arrow, which becomes an unclickable-looking dead
   zone once the sidebar is collapsed. Force them to the theme's text color. */
[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"] *,
[data-testid="stSidebar"] button,
[data-testid="stSidebar"] button *,
[data-testid="stHeader"] button,
[data-testid="stHeader"] button * {
    color: var(--text-primary) !important;
}

/* The re-expand control is also tiny (28px) and blends into the header
   even once correctly colored -- give it its own visible pill so it
   reads as an obvious button rather than a hard-to-spot glyph, since a
   user who once collapses the sidebar has no other way back in. */
[data-testid="stExpandSidebarButton"] {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-subtle) !important;
    border-radius: 8px !important;
}
[data-testid="stExpandSidebarButton"]:hover {
    border-color: var(--accent) !important;
}

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    max-width: 1400px;
}

[data-testid="stSidebar"] {
    background: var(--bg-card);
    border-right: 1px solid var(--border-subtle);
}
/* Soften the default Streamlit page-nav so the sidebar reads as part of the
   Ledger rather than stock chrome: roomier links, a hairline-free hover fill,
   and the bottle-green accent bar on the active page. */
[data-testid="stSidebarNav"] { padding-top: 0.5rem; }
[data-testid="stSidebarNav"] a {
    border-radius: 5px; margin: 1px 6px; padding-top: 0.35rem; padding-bottom: 0.35rem;
    transition: background 0.15s ease;
}
[data-testid="stSidebarNav"] a:hover { background: var(--bg-card-hover) !important; }
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNavLink"][aria-current="page"] {
    background: rgba(30,91,59,0.09) !important;
    box-shadow: inset 3px 0 0 var(--accent) !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--accent) !important; font-weight: 600; }
[data-testid="stSidebarNav"] a span { font-size: 0.92rem; }

/* Numeric readouts and tables in monospace for a terminal feel */
[data-testid="stDataFrame"], .kpi-value, code {
    font-family: var(--font-mono) !important;
}

hr { border-color: var(--border-subtle); }

/* --- App header --- */
.app-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 1px solid var(--border-subtle);
    padding-bottom: 0.9rem;
    margin-bottom: 1.6rem;
}
.app-header .page-title {
    font-family: var(--font-serif);
    font-size: 1.95rem;
    font-weight: 600;
    letter-spacing: -0.005em;
    color: var(--text-primary) !important;
}
.app-header .page-subtitle {
    color: var(--text-muted);
    font-size: 0.94rem;
    margin-top: 0.2rem;
}
.app-header .app-name {
    font-size: 0.74rem;
    letter-spacing: 0.03em;
    color: var(--text-muted);
}

/* --- Hero (Home page) --- */
.hero {
    padding: 2.2rem 0 1.6rem 0;
}
.hero .eyebrow {
    font-family: var(--font-serif);
    font-style: italic;
    color: var(--gold);
    font-size: 1.02rem;
    font-weight: 400;
    letter-spacing: 0;
    margin-bottom: 0.7rem;
}
.hero h1 {
    font-family: var(--font-serif);
    font-size: 2.9rem;
    font-weight: 700;
    letter-spacing: -0.015em;
    margin: 0 0 0.7rem 0;
    line-height: 1.12;
}
.hero p {
    color: var(--text-muted);
    font-size: 1.06rem;
    max-width: 680px;
    line-height: 1.6;
}

/* --- KPI cards --- */
.kpi-card {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 5px;
    padding: 1rem 1.1rem;
    min-height: 92px;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    transition: border-color 0.15s ease;
}
.kpi-card:hover { border-color: rgba(30,91,59,0.55); }
.kpi-label {
    color: var(--text-muted);
    font-size: 0.76rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    display: flex;
    align-items: center;
    gap: 0.3rem;
}
.kpi-value {
    font-size: 1.75rem;
    font-weight: 500;
    color: var(--text-primary);
    margin-top: 0.35rem;
    letter-spacing: -0.01em;
    line-height: 1.2;
}
.kpi-delta {
    font-size: 0.85rem;
    font-weight: 500;
    margin-top: auto;
    padding-top: 0.3rem;
}
.kpi-help { opacity: 0.5; font-size: 0.75rem; cursor: help; }

/* --- Bordered input/control groups (st.container(border=True)) --- */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 6px !important;
}

/* --- Section labels: set like a heading in a research note, not a
   wide-tracked all-caps micro-label. --- */
.section-label {
    font-family: var(--font-serif);
    font-size: 1.12rem;
    font-weight: 600;
    letter-spacing: -0.005em;
    color: var(--text-primary);
    margin: 1.9rem 0 0.8rem 0;
    padding-bottom: 0.45rem;
    border-bottom: 1px solid var(--border-subtle);
}

/* --- Status panel --- */
.status-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border-subtle);
}
.status-row:last-child { border-bottom: none; }
.status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--positive);
    flex-shrink: 0;
}
.status-label { font-size: 0.92rem; color: var(--text-primary); }
.status-note { font-size: 0.8rem; color: var(--text-muted); margin-left: auto; }

/* --- Nav / quick-link cards --- */
.nav-card {
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 5px;
    padding: 1rem 1.1rem;
    margin-bottom: 0.6rem;
}
/* Force the quick-link cards to a single uniform height so the row reads as a
   set and the "Open ..." links below them all sit on one baseline, instead of
   each card sizing to its own description length. Streamlit nests the card
   several wrappers deep (stElementContainer > stMarkdown > div >
   stMarkdownContainer), so the stretch has to be threaded through each one. */
[data-testid="stHorizontalBlock"] { align-items: stretch; }
[data-testid="stColumn"] { display: flex; flex-direction: column; }
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] { flex: 1 1 auto; }
[data-testid="stColumn"] [data-testid="stElementContainer"]:has(.nav-card),
[data-testid="stColumn"] [data-testid="stMarkdown"]:has(.nav-card),
[data-testid="stColumn"] [data-testid="stMarkdown"]:has(.nav-card) > div,
[data-testid="stColumn"] [data-testid="stMarkdownContainer"]:has(.nav-card) {
    display: flex; flex: 1 1 auto; width: 100%;
    /* Streamlit centres this wrapper's child by default, which leaves the card
       floating at its natural height instead of filling the column. */
    align-items: stretch !important;
}
.nav-card {
    transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease;
    min-height: 152px; display: flex; flex-direction: column;
    flex: 1 1 auto; width: 100%;
}
.nav-card .nav-desc { flex: 1 1 auto; }
.nav-card:hover {
    transform: translateY(-3px);
    border-color: var(--gold);
    background: var(--bg-card-hover);
}
.nav-card .nav-title {
    font-family: var(--font-serif);
    font-weight: 600;
    font-size: 1.08rem;
    letter-spacing: -0.005em;
    color: var(--text-primary) !important;
}
.nav-card .nav-desc { color: var(--text-muted); font-size: 0.85rem; margin-top: 0.25rem; line-height: 1.45; }

/* --- Motion: gentle entrance + a live, breathing status dot --- */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes livePulse {
    0%   { box-shadow: 0 0 0 0 rgba(30,91,59,0.5); }
    70%  { box-shadow: 0 0 0 7px rgba(30,91,59,0); }
    100% { box-shadow: 0 0 0 0 rgba(30,91,59,0); }
}
.kpi-card:hover { transform: translateY(-2px); }

/* --- Masthead: the Home page set like the front page of a rates note --- */
.masthead { animation: fadeUp 0.6s ease both; padding: 1.2rem 0 0.2rem; }
.masthead .edition {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.76rem; letter-spacing: 0.06em; color: var(--text-muted);
    text-transform: uppercase;
    border-top: 2px solid var(--text-primary);
    border-bottom: 1px solid var(--border-subtle);
    padding: 0.45rem 0;
}
.masthead .edition .place { color: var(--gold); }
.masthead h1 {
    font-family: var(--font-serif); font-weight: 700;
    font-size: 3.3rem; line-height: 1.04; letter-spacing: -0.02em;
    margin: 1.1rem 0 0.5rem;
    color: var(--text-primary) !important;
}
.masthead .standfirst {
    font-family: var(--font-serif); font-style: italic;
    color: var(--text-muted); font-size: 1.16rem; max-width: 700px; line-height: 1.5;
}
.masthead .byline {
    margin-top: 1rem; font-size: 0.88rem; color: var(--text-muted);
    border-top: 1px solid var(--border-subtle); padding-top: 0.75rem;
    display: flex; justify-content: space-between; align-items: baseline;
    gap: 1rem; flex-wrap: wrap;
}
.masthead .byline b { color: var(--text-primary); font-weight: 600; }
.byline-links { display: flex; gap: 1.25rem; flex-shrink: 0; }
.byline-links a {
    color: var(--accent); text-decoration: none; font-weight: 500;
    border-bottom: 1px solid transparent; transition: border-color 0.15s ease;
}
.byline-links a:hover { border-bottom-color: var(--accent); }

/* --- Methodology prose (Home) --- */
.methodology { max-width: 78ch; }
.methodology p {
    color: var(--text-muted); font-size: 0.97rem; line-height: 1.65;
    margin: 0 0 0.85rem 0;
}
.methodology p:last-child { margin-bottom: 0; }

/* --- Editor's note: a first-person voice, set like a pull-quote --- */
.editors-note {
    border-left: 3px solid var(--gold);
    padding: 0.1rem 0 0.1rem 1.15rem; margin: 1.7rem 0 0.3rem;
    font-family: var(--font-serif); font-size: 1.12rem; line-height: 1.62;
    color: var(--text-primary); max-width: 780px;
}
.editors-note .sig {
    display: block; margin-top: 0.55rem; font-style: italic;
    color: var(--text-muted); font-size: 0.95rem;
}

/* --- Live market tape --- */
.tape {
    display: flex; flex-wrap: wrap;
    border: 1px solid var(--border-subtle); border-radius: 6px;
    overflow: hidden; margin: 0.4rem 0 0; background: var(--bg-card);
}
.tape .tape-item {
    flex: 1 1 0; min-width: 120px; padding: 1.25rem 1.3rem;
    border-right: 1px solid var(--border-subtle);
}
.tape .tape-item:last-child { border-right: none; }
.tape .tape-key {
    font-size: 0.74rem; color: var(--text-muted); letter-spacing: 0.06em;
    text-transform: uppercase; font-weight: 500;
}
.tape .tape-val {
    font-family: var(--font-mono); font-size: 2rem; font-weight: 500;
    color: var(--text-primary); margin-top: 0.5rem; letter-spacing: -0.02em;
    line-height: 1.05;
}
.tape-line {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 0.8rem; color: var(--text-muted); margin: 0.6rem 0 0;
}
.tape-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--positive); animation: livePulse 2.4s infinite;
}

/* --- Kicker: a small serif label above a lead element --- */
.kicker {
    font-family: var(--font-serif); font-style: italic;
    color: var(--gold); font-size: 1rem; margin: 1.6rem 0 0.5rem;
}

/* --- Colophon ("how it's built") set as a ledger, not a status page --- */
.colophon-item {
    display: flex; justify-content: space-between; align-items: baseline;
    padding: 0.5rem 0; border-bottom: 1px dotted var(--border-subtle);
    font-size: 0.92rem;
}
.colophon-item:last-child { border-bottom: none; }
.colophon-item .c-k { color: var(--text-primary); }
.colophon-item .c-v { color: var(--text-muted); font-family: var(--font-mono); font-size: 0.82rem; }
.colophon-item .c-v.ok { color: var(--positive); }

/* --- Sign-off --- */
.signoff {
    font-family: var(--font-serif); font-style: italic;
    color: var(--text-muted); font-size: 0.95rem; line-height: 1.6;
    border-top: 1px solid var(--border-subtle); padding-top: 1rem; margin-top: 0.5rem;
}
</style>
"""


def apply_page_config(page_title: str) -> None:
    st.set_page_config(
        page_title=f"{page_title} | {APP_NAME}",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_FONT_LINKS, unsafe_allow_html=True)
    st.markdown(_CSS, unsafe_allow_html=True)


def render_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""<div class="app-header">
            <div>
                <div class="page-title">{title}</div>
                <div class="page-subtitle">{subtitle}</div>
            </div>
            <div class="app-name">{APP_NAME}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_section_label(label: str) -> None:
    st.markdown(f'<div class="section-label">{label}</div>', unsafe_allow_html=True)


def render_status_row(label: str, ok: bool = True, note: str = "") -> None:
    color = "var(--positive)" if ok else "var(--negative)"
    st.markdown(
        f"""<div class="status-row">
            <div class="status-dot" style="background:{color}"></div>
            <div class="status-label">{label}</div>
            <div class="status-note">{note}</div>
        </div>""",
        unsafe_allow_html=True,
    )
