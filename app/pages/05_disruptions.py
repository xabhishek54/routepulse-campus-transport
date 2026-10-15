"""
Page 5 — Disruptions & Replanning
Named disruption scenarios, before/after metrics, recovery analysis.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Disruptions — RoutePulse", page_icon="🌪️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: linear-gradient(135deg, #0a0e1a 0%, #0f1629 100%); color: #e2e8f0; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, #0d1526 0%, #111b33 100%); }
h1 { color: #63b3ed !important; } h2 { color: #90cdf4 !important; } h3 { color: #bee3f8 !important; }
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, rgba(26,54,93,0.6), rgba(17,37,68,0.8));
    border: 1px solid rgba(99,179,237,0.2); border-radius: 12px; padding: 16px;
}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def load_data():
    from routepulse.data_gen import build_campus, build_baseline_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    return stops, routes, vehicles, departures, baseline


@st.cache_data
def run_scenario(scenario_id, seed):
    from routepulse.data_gen import build_campus, build_baseline_plan
    from routepulse.simulator import simulate_plan
    from routepulse.scenarios import get_all_scenarios
    from routepulse.detector import detect_all
    from routepulse.optimizer import build_recommended_plan
    from routepulse.evaluator import compute_metrics
    from routepulse.validator import validate

    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    all_scenarios = get_all_scenarios(baseline)
    scenario_map = {s.scenario_id: s for s in all_scenarios}
    scenario = scenario_map[scenario_id]

    # Baseline (no disruption)
    trips_normal = simulate_plan(baseline, base_seed=seed)
    m_normal = compute_metrics(baseline, trips_normal, seed)

    # With disruption, no replan (do-nothing)
    trips_dis = simulate_plan(baseline, base_seed=seed, disruptions=scenario.disruptions)
    m_dis = compute_metrics(baseline, trips_dis, seed)

    # With disruption + RoutePulse replan
    det_dis = detect_all(baseline, trips_dis)
    replan = build_recommended_plan(baseline, trips_dis, det_dis["missed_connections"])
    trips_replan = simulate_plan(replan, base_seed=seed, disruptions=scenario.disruptions)
    m_replan = compute_metrics(replan, trips_replan, seed)

    val_replan = validate(replan)

    return scenario, trips_normal, trips_dis, trips_replan, m_normal, m_dis, m_replan, val_replan, replan


stops, routes, vehicles, departures, baseline = load_data()

# Scenario list
from routepulse.scenarios import get_all_scenarios
scenarios = get_all_scenarios(baseline)
scenario_map = {s.scenario_id: s for s in scenarios}

st.title("🌪️ Disruptions & Replanning")
st.caption("Live disruption simulation with RoutePulse replan and recovery measurement")

col_ctrl1, col_ctrl2 = st.columns([3, 1])
with col_ctrl1:
    scenario_options = {s.name: s.scenario_id for s in scenarios}
    sel_scenario_name = st.selectbox("Select Disruption Scenario", list(scenario_options.keys()))
    sel_scenario_id = scenario_options[sel_scenario_name]
with col_ctrl2:
    seed = st.number_input("Seed", value=42, min_value=42, max_value=52, step=1)

with st.spinner("Simulating disruption and generating replan..."):
    (
        scenario, trips_normal, trips_dis, trips_replan,
        m_normal, m_dis, m_replan,
        val_replan, replan
    ) = run_scenario(sel_scenario_id, int(seed))

# ── Scenario description ───────────────────────────────────────────────────────
st.info(f"**{scenario.name}**: {scenario.description}")

# ── Validation badge ───────────────────────────────────────────────────────────
ok = val_replan.passed
badge_color = "#276749" if ok else "#742a2a"
badge_bg = "rgba(39,103,73,0.2)" if ok else "rgba(116,42,42,0.2)"
st.markdown(
    f'<div style="background:{badge_bg};border:1px solid {badge_color};border-radius:8px;'
    f'padding:10px;display:inline-block;margin-bottom:12px">'
    f'{"✅ Replan passes all hard constraints" if ok else f"❌ Replan has {val_replan.n_violations} constraint violations"}</div>',
    unsafe_allow_html=True,
)

st.divider()

# ── Before / After metrics ────────────────────────────────────────────────────
st.subheader("Recovery Metrics")

metric_defs = [
    ("Overcrowding Events", "overcrowding_events", False),
    ("Unmet Demand", "total_unmet_demand", False),
    ("Missed Connections", "missed_connections", False),
    ("Avg Wait (min)", "average_wait_minutes", False),
    ("ETA MAE (min)", "eta_mae_minutes", False),
    ("Fleet Utilisation", "fleet_utilisation", True),
]

# Headline row: 3 states
st.markdown("**Normal → Disrupted → Replan**")
cols = st.columns(len(metric_defs))
for col, (label, key, hib) in zip(cols, metric_defs):
    nv = m_normal[key]
    dv = m_dis[key]
    rv = m_replan[key]
    # Delta: replan vs disrupted (positive = replan better)
    delta = nv - rv  # how much we recovered toward normal
    col.metric(
        label,
        value=round(rv, 2),
        delta=f"Disrupted: {round(dv, 2)} | Normal: {round(nv, 2)}",
    )

st.divider()

# ── Comparison bar chart ───────────────────────────────────────────────────────
st.subheader("Before / During / After Disruption")
plot_keys = ["overcrowding_events", "total_unmet_demand", "missed_connections", "average_wait_minutes"]
plot_labels = ["Overcrowding", "Unmet Demand", "Missed Connections", "Avg Wait (min)"]

fig = go.Figure()
x = plot_labels
for name, m, color in [
    ("Normal",   m_normal, "#63b3ed"),
    ("Disrupted (no replan)", m_dis, "#fc8181"),
    ("Replan",   m_replan, "#68d391"),
]:
    fig.add_trace(go.Bar(
        name=name,
        x=x,
        y=[m[k] for k in plot_keys],
        marker_color=color,
        opacity=0.85,
    ))

fig.update_layout(
    barmode="group",
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=320,
    margin=dict(l=0, r=0, t=20, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    xaxis_title="Metric",
    yaxis_title="Value",
)
st.plotly_chart(fig, use_container_width=True)

# ── Recovery score ─────────────────────────────────────────────────────────────
st.subheader("Recovery Score")

def recovery_score(m_normal, m_dis, m_replan, keys, inverts):
    """% of disruption impact recovered by the replan."""
    scores = []
    for k, inv in zip(keys, inverts):
        n, d, r = m_normal[k], m_dis[k], m_replan[k]
        impact = d - n  # how bad disruption made it
        if abs(impact) < 0.01:
            scores.append(1.0)
            continue
        recovery = (d - r) / impact  # how much we got back
        scores.append(max(0.0, min(1.0, recovery)))
    return sum(scores) / len(scores)

keys_for_score = ["overcrowding_events", "total_unmet_demand", "missed_connections", "average_wait_minutes"]
inverts = [False, False, False, False]
score = recovery_score(m_normal, m_dis, m_replan, keys_for_score, inverts)

c1, c2 = st.columns([1, 3])
with c1:
    color = "#68d391" if score > 0.6 else ("#f6ad55" if score > 0.3 else "#fc8181")
    st.markdown(
        f'<div style="text-align:center;padding:20px;background:rgba(0,0,0,0.3);border-radius:16px;'
        f'border:2px solid {color}">'
        f'<div style="font-size:48px;font-weight:700;color:{color}">{score:.0%}</div>'
        f'<div style="color:#a0aec0;font-size:14px">Recovery Score</div></div>',
        unsafe_allow_html=True,
    )
with c2:
    st.markdown("""
**Recovery Score** = fraction of disruption impact recovered by the replan.

- **100%** = replan fully restores normal operations
- **>60%** = good recovery (green)
- **30–60%** = partial recovery (amber)  
- **<30%** = limited recovery — disruption dominates (red)

The score is averaged across: overcrowding, unmet demand, missed connections, and average wait time.
""")

# ── Replan actions ─────────────────────────────────────────────────────────────
st.subheader("Replan Actions Applied")
if replan.actions_applied:
    for i, action in enumerate(replan.actions_applied, 1):
        icon = {"vehicle_swap": "🚌", "extra_trip": "➕", "departure_nudge": "⏰"}.get(action.action_type, "•")
        st.markdown(f"**{icon} {i}.** {action.description}  \n"
                    f"↳ *Cost:* {action.cost_label} | *Benefit:* {action.benefit_label}")
else:
    st.info("No replan actions generated (disruption impact within tolerance).")
