"""
Shared utilities for the RoutePulse Streamlit app.

All pages import from this module to avoid:
  - Duplicate CSS blocks
  - Duplicate load_campus() definitions
  - Inconsistent caching strategies
"""
from __future__ import annotations
import os
import sys

# Ensure the repo root is on the path regardless of where Streamlit is invoked
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

# ---------------------------------------------------------------------------
# Shared CSS — injected once per page
# ---------------------------------------------------------------------------
DARK_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp {
    background: linear-gradient(135deg, #0a0e1a 0%, #0f1629 50%, #0a1520 100%);
    color: #e2e8f0;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1526 0%, #111b33 100%);
    border-right: 1px solid rgba(99, 179, 237, 0.15);
}

div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(26,54,93,0.6) 0%, rgba(17,37,68,0.8) 100%);
    border: 1px solid rgba(99,179,237,0.2);
    border-radius: 12px;
    padding: 16px;
    backdrop-filter: blur(10px);
    transition: transform 0.2s ease, border-color 0.2s ease;
}
div[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    border-color: rgba(99,179,237,0.5);
}

h1 { color: #63b3ed !important; font-weight: 700 !important; letter-spacing: -0.5px; }
h2 { color: #90cdf4 !important; font-weight: 600 !important; }
h3 { color: #bee3f8 !important; font-weight: 500 !important; }

.dataframe { font-size: 13px !important; }

.stTabs [data-baseweb="tab"] { color: #90cdf4; border-bottom: 2px solid transparent; }
.stTabs [aria-selected="true"] { border-bottom: 2px solid #63b3ed !important; color: #63b3ed !important; }

.stButton > button {
    background: linear-gradient(135deg, #2b6cb0, #1a4f8a);
    color: white; border: none; border-radius: 8px; font-weight: 500;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #3182ce, #2c5282);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(49,130,206,0.3);
}
.stProgress > div > div { background: linear-gradient(90deg, #2b6cb0, #63b3ed); }
</style>
"""


def inject_css() -> None:
    """Inject the shared dark theme CSS into the current page."""
    st.markdown(DARK_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Shared campus data — cached globally across pages via session state
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="🚌 Loading campus data…")
def load_campus():
    """
    Build and cache the Westbrook University campus objects.
    Returns (stops, routes, vehicles, departures, baseline_plan, smarter_plan).
    """
    from routepulse.data_gen import build_campus, build_baseline_plan, build_smarter_baseline_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    smarter  = build_smarter_baseline_plan(stops=stops, routes=routes, vehicles=vehicles)
    return stops, routes, vehicles, departures, baseline, smarter


@st.cache_data(show_spinner="⚙️ Running simulation…")
def get_simulation(plan_id: str, seed: int, disruption_ids: tuple = ()):
    """
    Simulate a named plan under optional disruptions.
    plan_id: 'baseline_naive' | 'baseline_smarter'
    disruption_ids: tuple of scenario_id strings (hashable for caching)
    """
    from routepulse.simulator import simulate_plan
    from routepulse.scenarios import get_all_scenarios

    stops, routes, vehicles, departures, baseline, smarter = load_campus()
    plans = {"baseline_naive": baseline, "baseline_smarter": smarter}
    plan = plans.get(plan_id, baseline)

    all_scenarios = get_all_scenarios(plan)
    scenario_map = {s.scenario_id: s for s in all_scenarios}
    disruptions = []
    for sid in disruption_ids:
        if sid in scenario_map:
            disruptions.extend(scenario_map[sid].disruptions)

    return simulate_plan(plan, base_seed=seed, disruptions=disruptions or None)


@st.cache_resource(show_spinner="🤖 Training demand forecaster…")
def get_forecaster():
    """
    Train and cache the ML demand forecaster using seeds 42–47 (train) and 48–52 (holdout).
    This is expensive to train once, then cached for the session.
    """
    from routepulse.forecaster import train_forecaster
    from routepulse.config import EVAL_SEEDS
    n = len(EVAL_SEEDS)
    train_seeds   = EVAL_SEEDS[:n // 2]
    holdout_seeds = EVAL_SEEDS[n // 2:]
    return train_forecaster(train_seeds=train_seeds, holdout_seeds=holdout_seeds)


# ---------------------------------------------------------------------------
# Time formatting helper (used by all pages)
# ---------------------------------------------------------------------------
def fmt_time(minutes: float) -> str:
    """Convert minutes-since-midnight to HH:MM string."""
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# Validation badge helper
# ---------------------------------------------------------------------------
def validation_badge(plan_name: str, val_report) -> None:
    """Render a coloured validation badge for a plan."""
    ok = val_report.passed
    color = "#276749" if ok else "#742a2a"
    bg    = "rgba(39,103,73,0.2)" if ok else "rgba(116,42,42,0.2)"
    icon  = "✅ VALID" if ok else f"❌ {val_report.n_violations} violations"
    st.markdown(
        f'<div style="background:{bg};border:1px solid {color};border-radius:10px;'
        f'padding:12px;text-align:center">'
        f'<b style="font-size:12px;color:#a0aec0">{plan_name}</b><br>'
        f'<span style="font-size:18px;font-weight:700;color:{"#68d391" if ok else "#fc8181"}">'
        f'{icon}</span></div>',
        unsafe_allow_html=True,
    )
