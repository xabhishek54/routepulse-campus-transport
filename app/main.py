"""
RoutePulse — Streamlit Dashboard Landing Page
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from app.utils import inject_css, load_campus, fmt_time

st.set_page_config(
    page_title="RoutePulse — Campus Transport Optimiser",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ── Header ─────────────────────────────────────────────────────────────────────
col1, col2 = st.columns([3, 1])
with col1:
    st.title("🚌 RoutePulse")
    st.markdown(
        "**Campus Transport Optimiser** — Westbrook University  \n"
        "Arrival estimation · ML demand forecasting · Schedule optimisation · Disruption replanning"
    )
with col2:
    st.markdown("")
    st.markdown(
        '<div style="text-align:right;color:#4a5568;font-size:12px">'
        'Hackathon: Wild Bugs<br>Problem: Campus Transport<br>Seed: 42–52</div>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Quick stats ────────────────────────────────────────────────────────────────
stops, routes, vehicles, departures, baseline, smarter = load_campus()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Campus Stops", len(stops))
c2.metric("Routes", len(routes))
c3.metric("Departures / Day", len(departures))
c4.metric("Vehicles", len(vehicles))
c5.metric("Eval Seeds", "42 – 52")

st.divider()

# ── Feature table ──────────────────────────────────────────────────────────────
st.markdown("""
### What RoutePulse Does

| Page | Capability |
|------|-----------|
| 🗺️ **Overview** | Interactive campus map, route explorer, demand curve |
| ⏱️ **Arrivals** | Kalman-filter ETA windows with 90% confidence intervals and calibration |
| ⚠️ **Violations** | Independent constraint validator, overcrowding heatmap, missed connections |
| 🤖 **Forecasting** | ML demand forecaster (Gradient Boosting) — per-stop horizon predictions with uncertainty |
| 🔧 **Recommendations** | Vehicle swaps, extra trips, departure nudges — all validated before display |
| 🌪️ **Disruptions** | Four named scenarios with live replanning and recovery score |

👈 Use the sidebar to navigate.
""")

st.divider()

# ── Architecture info ──────────────────────────────────────────────────────────
with st.expander("ℹ️ System Architecture & Methodology", expanded=False):
    st.markdown("""
**Arrival estimation** — 1D Kalman filter tracks delay state stop-by-stop.
Process noise = 0.25 min/stop (uncertainty grows with distance). Observation noise = 0.3 min.
CI half-width = z₀.₀₅ × predicted std. Calibration measured independently.

**Demand forecasting (ML)** — `GradientBoostingRegressor` trained on multi-seed simulations.
Features: cyclic time encoding (sin/cos), lag boarding counts, demand multiplier, stop identity (ordinal).
Train seeds: 42–47. Holdout seeds: 48–52. Reports train MAE and holdout MAE separately.

**Optimizer** — greedy heuristics: vehicle swap → extra trip → departure nudge.
Every recommended plan is checked by the independent constraint validator before display.
Hard constraints: capacity, headway ≥ 5 min, operating window 08:00–20:00.

**Evaluation** — 11 seeds (42–52), fixed synthetic data, reproducible via `python eval/run_evaluation.py`.
""")

st.markdown("""
---
<div style="color:#4a5568;font-size:11px">
Westbrook University is a fictional synthetic campus. No real passenger data used.<br>
Reproduce all results: <code>python eval/run_evaluation.py</code> &nbsp;|&nbsp;
Tests: <code>pytest tests/ -v</code>
</div>
""", unsafe_allow_html=True)
