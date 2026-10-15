"""
RoutePulse — Streamlit Dashboard
Main entry point and shared state management.
"""
import sys
import os

# Allow importing the routepulse package from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(
    page_title="RoutePulse — Campus Transport Optimiser",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* Dark gradient background */
.stApp {
    background: linear-gradient(135deg, #0a0e1a 0%, #0f1629 50%, #0a1520 100%);
    color: #e2e8f0;
}

/* Sidebar */
.css-1d391kg, [data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1526 0%, #111b33 100%);
    border-right: 1px solid rgba(99, 179, 237, 0.15);
}

/* Metric cards */
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

/* Headers */
h1 { color: #63b3ed !important; font-weight: 700 !important; letter-spacing: -0.5px; }
h2 { color: #90cdf4 !important; font-weight: 600 !important; }
h3 { color: #bee3f8 !important; font-weight: 500 !important; }

/* Dataframes */
.dataframe { font-size: 13px !important; }

/* Status badges */
.badge-ok   { background: #276749; color: #9ae6b4; padding: 2px 10px; border-radius: 99px; font-size: 12px; }
.badge-warn { background: #744210; color: #fbd38d; padding: 2px 10px; border-radius: 99px; font-size: 12px; }
.badge-fail { background: #742a2a; color: #feb2b2; padding: 2px 10px; border-radius: 99px; font-size: 12px; }

/* Tabs */
.stTabs [data-baseweb="tab"] {
    color: #90cdf4;
    border-bottom: 2px solid transparent;
}
.stTabs [aria-selected="true"] {
    border-bottom: 2px solid #63b3ed !important;
    color: #63b3ed !important;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #2b6cb0, #1a4f8a);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #3182ce, #2c5282);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(49,130,206,0.3);
}

/* Selectbox, sliders */
.stSelectbox > div > div, .stSlider > div {
    color: #bee3f8;
}

/* Info/warning boxes */
.stAlert { border-radius: 10px; }

/* Progress bars */
.stProgress > div > div { background: linear-gradient(90deg, #2b6cb0, #63b3ed); }
</style>
""", unsafe_allow_html=True)

# ── Cached data ───────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Building campus data...")
def load_campus():
    from routepulse.data_gen import build_campus, build_baseline_plan, build_smarter_baseline_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    smarter  = build_smarter_baseline_plan(stops=stops, routes=routes, vehicles=vehicles)
    return stops, routes, vehicles, departures, baseline, smarter


@st.cache_data(show_spinner="Running simulation...")
def run_simulation(plan_id: str, seed: int, disruption_ids: tuple = ()):
    from routepulse.data_gen import build_campus, build_baseline_plan, build_smarter_baseline_plan
    from routepulse.simulator import simulate_plan
    from routepulse.scenarios import get_all_scenarios

    stops, routes, vehicles, departures, baseline, smarter = load_campus()
    plans = {"baseline_naive": baseline, "baseline_smarter": smarter}
    plan = plans.get(plan_id, baseline)

    # Resolve disruptions
    all_scenarios = get_all_scenarios(plan)
    scenario_map = {s.scenario_id: s for s in all_scenarios}
    disruptions = []
    for sid in disruption_ids:
        if sid in scenario_map:
            disruptions.extend(scenario_map[sid].disruptions)

    trips = simulate_plan(plan, base_seed=seed, disruptions=disruptions or None)
    return trips


# ── Landing page ──────────────────────────────────────────────────────────────
col1, col2 = st.columns([3, 1])
with col1:
    st.title("🚌 RoutePulse")
    st.markdown(
        "**Campus Transport Optimiser** — Westbrook University  \n"
        "Arrival estimation · Demand forecasting · Schedule optimisation · Disruption replanning"
    )
with col2:
    st.markdown("")
    st.markdown("")
    st.markdown(
        '<div style="text-align:right;color:#4a5568;font-size:12px">Hackathon: Wild Bugs<br>Problem: Campus Transport</div>',
        unsafe_allow_html=True,
    )

st.divider()

# Quick stats
stops, routes, vehicles, departures, baseline, smarter = load_campus()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stops", len(stops))
c2.metric("Routes", len(routes))
c3.metric("Departures / Day", len(departures))
c4.metric("Vehicles", len(vehicles))

st.divider()

st.markdown("""
### What RoutePulse does

| Capability | Description |
|-----------|-------------|
| 🗺️ **Route Explorer** | Visualise all stops, routes, and schedules on an interactive campus map |
| ⏱️ **Arrival Estimates** | Kalman-filtered ETA windows with honest confidence intervals |
| ⚠️ **Violation Detection** | Overcrowding, schedule conflicts, and missed connections — flagged in real time |
| 🔧 **Plan Optimiser** | Vehicle upgrades, extra trips, departure nudges — all validated against hard constraints |
| 🌪️ **Disruption Replay** | Named disruption scenarios with live replanning and recovery metrics |

👈 Use the sidebar to navigate to each page.
""")

st.markdown("""
---
<div style="color:#4a5568;font-size:11px">
All data is synthetic (fixed seed=42). No real passenger data. 
Results are reproducible: <code>python eval/run_evaluation.py</code>
</div>
""", unsafe_allow_html=True)
