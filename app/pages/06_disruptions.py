"""
Page 6 — Disruptions & Replanning
Named scenarios · 3-state comparison · recovery score · action list.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from app.utils import inject_css, load_campus, fmt_time, validation_badge
from routepulse.simulator import simulate_plan
from routepulse.scenarios import get_all_scenarios
from routepulse.detector import detect_all
from routepulse.optimizer import build_recommended_plan
from routepulse.evaluator import compute_metrics
from routepulse.validator import validate
from routepulse.config import SEED

inject_css()

stops, routes, vehicles, departures, baseline, smarter = load_campus()

st.title("🌪️ Disruptions & Replanning")
st.caption("Simulate named disruptions and measure RoutePulse recovery")

all_scenarios = get_all_scenarios(baseline)
scenario_map  = {s.scenario_id: s for s in all_scenarios}

col_ctrl1, col_ctrl2 = st.columns([3, 1])
with col_ctrl1:
    sel_name = st.selectbox("Disruption Scenario", [s.name for s in all_scenarios])
    sel_scenario = next(s for s in all_scenarios if s.name == sel_name)
with col_ctrl2:
    seed = st.number_input("Seed", value=SEED, min_value=SEED, max_value=SEED + 10, step=1)

@st.cache_data(show_spinner="Simulating disruption + replan…")
def _run(scenario_id: str, seed_val: int):
    scenario = scenario_map[scenario_id]

    trips_normal = simulate_plan(baseline, base_seed=seed_val)
    trips_dis    = simulate_plan(baseline, base_seed=seed_val, disruptions=scenario.disruptions)

    det_dis  = detect_all(baseline, trips_dis)
    replan   = build_recommended_plan(baseline, trips_dis, det_dis["missed_connections"])
    trips_re = simulate_plan(replan,   base_seed=seed_val, disruptions=scenario.disruptions)

    m_normal = compute_metrics(baseline, trips_normal, seed_val)
    m_dis    = compute_metrics(baseline, trips_dis,    seed_val)
    m_re     = compute_metrics(replan,  trips_re,      seed_val)
    val_re   = validate(replan, trips_re)

    return scenario, trips_normal, trips_dis, trips_re, m_normal, m_dis, m_re, val_re, replan

with st.spinner("Running simulation…"):
    scenario, trips_normal, trips_dis, trips_re, m_normal, m_dis, m_re, val_re, replan = \
        _run(sel_scenario.scenario_id, int(seed))

st.info(f"**{scenario.name}**: {scenario.description}")

cancelled = len(baseline.departures) - len(trips_dis)
if cancelled > 0:
    st.warning(f"⚠️ {cancelled} trip(s) cancelled due to vehicle breakdown in this scenario.")

st.divider()
validation_badge("Replan", val_re)
st.divider()

# ── Metrics: 3-state ──────────────────────────────────────────────────────────
st.subheader("Recovery Metrics: Normal → Disrupted → Replan")
metric_defs = [
    ("Overcrowding",    "overcrowding_events",  False),
    ("Unmet Demand",    "total_unmet_demand",   False),
    ("Missed Conns",    "missed_connections",   False),
    ("Avg Wait (min)",  "average_wait_minutes", False),
    ("ETA MAE (min)",   "eta_mae_minutes",      False),
    ("Fleet Util",      "fleet_utilisation",    True),
]

cols = st.columns(len(metric_defs))
for col, (label, key, hib) in zip(cols, metric_defs):
    rv = m_re[key]; dv = m_dis[key]; nv = m_normal[key]
    delta_str = f"Disrupted: {round(dv,2)} | Normal: {round(nv,2)}"
    col.metric(label, value=round(rv, 2), delta=delta_str)

st.divider()

# ── Bar chart ─────────────────────────────────────────────────────────────────
st.subheader("Before / During / After Comparison")
plot_keys   = ["overcrowding_events", "total_unmet_demand", "missed_connections", "average_wait_minutes"]
plot_labels = ["Overcrowding", "Unmet Demand", "Missed Connections", "Avg Wait (min)"]

fig = go.Figure()
for name, m, color in [
    ("Normal",             m_normal, "#63b3ed"),
    ("Disrupted (no replan)", m_dis, "#fc8181"),
    ("Replan",              m_re,  "#68d391"),
]:
    fig.add_trace(go.Bar(name=name, x=plot_labels,
        y=[m[k] for k in plot_keys], marker_color=color, opacity=0.85))
fig.update_layout(barmode="group", template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    height=320, margin=dict(l=0,r=0,t=20,b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis_title="Metric", yaxis_title="Value")
st.plotly_chart(fig, use_container_width=True)

# ── Recovery score ─────────────────────────────────────────────────────────────
st.subheader("Recovery Score")

def _recovery(m_n, m_d, m_r, keys):
    scores = []
    for k in keys:
        n, d, r = m_n[k], m_d[k], m_r[k]
        impact = d - n
        if abs(impact) < 0.01:
            scores.append(1.0)
            continue
        scores.append(max(0.0, min(1.0, (d - r) / impact)))
    return sum(scores) / len(scores)

score = _recovery(m_normal, m_dis, m_re,
                  ["overcrowding_events", "total_unmet_demand", "missed_connections", "average_wait_minutes"])

c1, c2 = st.columns([1, 3])
with c1:
    color = "#68d391" if score > 0.6 else ("#f6ad55" if score > 0.3 else "#fc8181")
    st.markdown(
        f'<div style="text-align:center;padding:20px;background:rgba(0,0,0,0.3);'
        f'border-radius:16px;border:2px solid {color}">'
        f'<div style="font-size:48px;font-weight:700;color:{color}">{score:.0%}</div>'
        f'<div style="color:#a0aec0;font-size:14px">Recovery Score</div></div>',
        unsafe_allow_html=True,
    )
with c2:
    st.markdown("""
**Recovery Score** = fraction of disruption impact recovered by the replan.

| Score | Interpretation |
|-------|----------------|
| > 60% | 🟢 Good recovery |
| 30–60% | 🟡 Partial recovery |
| < 30% | 🔴 Disruption dominates |

Averaged across: overcrowding, unmet demand, missed connections, avg wait.
""")

# ── Replan actions ─────────────────────────────────────────────────────────────
st.subheader("Replan Actions Applied")
if replan.actions_applied:
    icons = {"vehicle_swap": "🚌", "extra_trip": "➕", "departure_nudge": "⏰"}
    for i, action in enumerate(replan.actions_applied, 1):
        icon = icons.get(action.action_type, "•")
        with st.expander(f"{icon} Action {i}: {action.description}", expanded=(i == 1)):
            col_x, col_y = st.columns(2)
            col_x.markdown(f"**Cost:** {action.cost_label}")
            col_y.markdown(f"**Benefit:** {action.benefit_label}")
else:
    st.info("No replan actions generated — disruption impact within tolerance.")
