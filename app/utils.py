"""
RoutePulse shared utilities — single source of truth for all pages.

Design principles:
  - Fonts are loaded from a bundled CSS string, NOT Google Fonts (works offline)
  - CSS is injected exactly once per page via inject_css()
  - load_campus() is @cache_resource — runs once for the whole session
  - All metric helpers live here so every page uses the same numbers
"""
from __future__ import annotations
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st


# ─── Design system ────────────────────────────────────────────────────────────
# Palette: deep navy background, electric blue accents, warm amber for warnings
ACCENT      = "#60a5fa"      # blue-400
ACCENT_DIM  = "#3b82f6"      # blue-500
SUCCESS     = "#34d399"      # emerald-400
WARNING     = "#fbbf24"      # amber-400
DANGER      = "#f87171"      # red-400
NEUTRAL     = "#94a3b8"      # slate-400
BG_DARK     = "#0c1220"
BG_CARD     = "rgba(15,23,42,0.85)"
BORDER      = "rgba(96,165,250,0.15)"
BORDER_ACTIVE = "rgba(96,165,250,0.5)"


DARK_CSS = f"""
<style>
/* ─── Typography: system fonts (no external requests, works offline) ─── */
html, body, [class*="css"] {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
}}

/* ─── Background ─── */
.stApp {{
    background: linear-gradient(135deg, {BG_DARK} 0%, #0f172a 60%, #0c1a2e 100%);
    color: #e2e8f0;
}}

/* ─── Sidebar ─── */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #0d1526 0%, #0f1e38 100%);
    border-right: 1px solid {BORDER};
}}
[data-testid="stSidebar"] .stMarkdown {{ color: #94a3b8; font-size: 13px; }}

/* ─── Headings ─── */
h1 {{ color: {ACCENT} !important; font-weight: 700 !important; letter-spacing: -0.5px; font-size: 2rem !important; }}
h2 {{ color: #93c5fd !important; font-weight: 600 !important; }}
h3 {{ color: #bfdbfe !important; font-weight: 500 !important; }}

/* ─── Metric cards ─── */
div[data-testid="metric-container"] {{
    background: linear-gradient(135deg, rgba(15,23,42,0.9) 0%, rgba(17,37,68,0.95) 100%);
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 18px 16px;
    backdrop-filter: blur(12px);
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}}
div[data-testid="metric-container"]:hover {{
    transform: translateY(-2px);
    border-color: {BORDER_ACTIVE};
    box-shadow: 0 8px 24px rgba(96,165,250,0.12);
}}
div[data-testid="metric-container"] [data-testid="stMetricLabel"] {{
    color: {NEUTRAL} !important;
    font-size: 12px !important;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 500;
}}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {{
    color: {ACCENT} !important;
    font-size: 1.6rem !important;
    font-weight: 700 !important;
}}

/* ─── Buttons ─── */
.stButton > button {{
    background: linear-gradient(135deg, {ACCENT_DIM}, #1d4ed8);
    color: white; border: none; border-radius: 10px;
    font-weight: 600; padding: 10px 22px;
    transition: all 0.2s ease; letter-spacing: 0.2px;
}}
.stButton > button:hover {{
    background: linear-gradient(135deg, {ACCENT}, {ACCENT_DIM});
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(96,165,250,0.35);
}}

/* ─── Tabs ─── */
.stTabs [data-baseweb="tab"] {{ color: {NEUTRAL}; border-bottom: 2px solid transparent; font-weight: 500; }}
.stTabs [aria-selected="true"] {{ border-bottom: 2px solid {ACCENT} !important; color: {ACCENT} !important; }}

/* ─── Dataframe ─── */
.dataframe {{ font-size: 13px !important; }}

/* ─── Progress bar ─── */
.stProgress > div > div {{ background: linear-gradient(90deg, {ACCENT_DIM}, {ACCENT}); border-radius: 4px; }}

/* ─── Selectbox / Slider ─── */
[data-baseweb="select"] {{ border-radius: 10px !important; }}

/* ─── Status cards ─── */
.rp-card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 20px 22px;
    margin-bottom: 12px;
    backdrop-filter: blur(10px);
    transition: border-color 0.2s ease;
}}
.rp-card:hover {{ border-color: {BORDER_ACTIVE}; }}

.rp-badge-ok {{
    display: inline-block;
    background: rgba(52,211,153,0.15);
    border: 1px solid rgba(52,211,153,0.4);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 12px;
    font-weight: 600;
    color: {SUCCESS};
}}
.rp-badge-warn {{
    display: inline-block;
    background: rgba(251,191,36,0.15);
    border: 1px solid rgba(251,191,36,0.4);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 12px;
    font-weight: 600;
    color: {WARNING};
}}
.rp-badge-bad {{
    display: inline-block;
    background: rgba(248,113,113,0.15);
    border: 1px solid rgba(248,113,113,0.4);
    border-radius: 20px;
    padding: 3px 12px;
    font-size: 12px;
    font-weight: 600;
    color: {DANGER};
}}
</style>
"""


def inject_css() -> None:
    """Inject the shared dark-theme CSS. Call once at the top of every page."""
    st.markdown(DARK_CSS, unsafe_allow_html=True)


def metric_badge(value, good_threshold=None, bad_threshold=None, higher_is_better=False) -> str:
    """Return CSS class for badge based on value direction."""
    if good_threshold is None:
        return "rp-badge-ok"
    if higher_is_better:
        if value >= good_threshold:
            return "rp-badge-ok"
        elif bad_threshold and value <= bad_threshold:
            return "rp-badge-bad"
        return "rp-badge-warn"
    else:
        if value <= good_threshold:
            return "rp-badge-ok"
        elif bad_threshold and value >= bad_threshold:
            return "rp-badge-bad"
        return "rp-badge-warn"


def fmt_time(minutes: float) -> str:
    """Convert minutes-since-midnight to HH:MM string."""
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}"


def fmt_delta(value: float, higher_is_better: bool = False) -> str:
    """Format a delta with directional arrow and colour hint."""
    if value == 0:
        return "—"
    arrow = "↑" if value > 0 else "↓"
    return f"{arrow} {abs(value):.1f}"


# ─── Cached data loaders ───────────────────────────────────────────────────────

@st.cache_resource(show_spinner="Loading campus data…")
def load_campus():
    """
    Build and cache Westbrook University campus data.
    Returns (stops, routes, vehicles, departures, naive_plan, smarter_plan).
    """
    from routepulse.data_gen import (
        build_campus, build_naive_baseline, build_smarter_baseline_plan
    )
    stops, routes, vehicles, departures = build_campus()
    naive   = build_naive_baseline(departures=departures)
    smarter = build_smarter_baseline_plan(routes=routes, vehicles=vehicles)
    return stops, routes, vehicles, departures, naive, smarter


@st.cache_data(show_spinner="Running simulation…", ttl=300)
def get_simulation(plan_id: str, seed: int, disruption_ids: tuple = ()):
    """
    Simulate a named plan under optional disruptions.
    plan_id: 'baseline_naive' | 'baseline_smarter' | 'optimised'
    """
    from routepulse.simulator import simulate_plan
    from routepulse.scenarios import get_all_scenarios
    from routepulse.detector import detect_all
    from routepulse.optimizer import build_recommended_plan

    stops, routes, vehicles, departures, naive, smarter = load_campus()
    plans = {"baseline_naive": naive, "baseline_smarter": smarter}

    if plan_id == "optimised":
        trips_n = simulate_plan(naive, base_seed=seed)
        det = detect_all(naive, trips_n)
        plan = build_recommended_plan(naive, trips_n, det["missed_connections"])
    else:
        plan = plans.get(plan_id, naive)

    all_scenarios = get_all_scenarios(plan)
    scenario_map = {s.scenario_id: s for s in all_scenarios}
    disruptions = []
    for sid in disruption_ids:
        if sid in scenario_map:
            disruptions.extend(scenario_map[sid].disruptions)

    return plan, simulate_plan(plan, base_seed=seed, disruptions=disruptions or None)


@st.cache_data(show_spinner="Evaluating all plans…", ttl=600)
def get_multi_seed_results(seeds: tuple):
    """Run all three plans under all seeds and return EvaluationResult objects."""
    from routepulse.evaluator import evaluate_plan_multi_seed

    stops, routes, vehicles, departures, naive, smarter = load_campus()

    # Build optimised plan using the default seed
    from routepulse.simulator import simulate_plan
    from routepulse.detector import detect_all
    from routepulse.optimizer import build_recommended_plan
    trips_n = simulate_plan(naive, base_seed=42)
    det = detect_all(naive, trips_n)
    optimised = build_recommended_plan(naive, trips_n, det["missed_connections"])

    seeds_list = list(seeds)
    er_naive     = evaluate_plan_multi_seed(naive, seeds_list)
    er_smarter   = evaluate_plan_multi_seed(smarter, seeds_list)
    er_optimised = evaluate_plan_multi_seed(optimised, seeds_list)
    return er_naive, er_smarter, er_optimised, optimised


@st.cache_resource(show_spinner="Training demand forecaster…")
def get_forecaster():
    """Train and cache the ML demand forecaster."""
    from routepulse.forecaster import train_forecaster
    from routepulse.config import EVAL_SEEDS
    n = len(EVAL_SEEDS)
    train_seeds   = EVAL_SEEDS[:n // 2]
    holdout_seeds = EVAL_SEEDS[n // 2:]
    return train_forecaster(train_seeds=train_seeds, holdout_seeds=holdout_seeds)


# ─── Shared UI helpers ─────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str) -> None:
    """Render a consistent page header with title and subtitle."""
    st.markdown(
        f'<div style="margin-bottom:24px">'
        f'<h1 style="margin-bottom:4px">{title}</h1>'
        f'<p style="color:{NEUTRAL};font-size:15px;margin:0">{subtitle}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: str, sub: str = "", color: str = ACCENT) -> str:
    """Return HTML for a stat card."""
    return (
        f'<div class="rp-card">'
        f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;'
        f'color:{NEUTRAL};margin-bottom:6px">{label}</div>'
        f'<div style="font-size:1.8rem;font-weight:700;color:{color};line-height:1">{value}</div>'
        f'<div style="font-size:12px;color:{NEUTRAL};margin-top:4px">{sub}</div>'
        f'</div>'
    )


def validation_badge(plan_name: str, val_report) -> None:
    """Render a coloured validation badge for a plan."""
    ok    = val_report.passed
    color = SUCCESS if ok else DANGER
    bg    = "rgba(52,211,153,0.12)" if ok else "rgba(248,113,113,0.12)"
    border = "rgba(52,211,153,0.35)" if ok else "rgba(248,113,113,0.35)"
    icon  = "All constraints satisfied" if ok else f"{val_report.n_violations} constraint violations"
    st.markdown(
        f'<div style="background:{bg};border:1px solid {border};border-radius:12px;'
        f'padding:14px;text-align:center">'
        f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;'
        f'color:{NEUTRAL};margin-bottom:4px">{plan_name}</div>'
        f'<div style="font-size:15px;font-weight:700;color:{color}">{icon}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
