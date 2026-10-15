"""
Page 5 — Plan Recommendations
Before/after comparison, radar chart, trade-off explorer, action details.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from app.utils import inject_css, load_campus, fmt_time, validation_badge
from routepulse.simulator import simulate_plan
from routepulse.detector import detect_all
from routepulse.optimizer import build_recommended_plan, tradeoff_summary
from routepulse.evaluator import compute_metrics
from routepulse.validator import validate
from routepulse.config import SEED

inject_css()

stops, routes, vehicles, departures, baseline, smarter = load_campus()

st.title("🔧 Plan Recommendations")
st.caption("Feasible schedule adjustments — validated against all hard constraints before display")

seed = st.sidebar.number_input("Simulation seed", value=SEED, min_value=SEED,
                                max_value=SEED + 10, step=1)

@st.cache_data(show_spinner="Generating recommendations…")
def _get_recommendation(seed_val):
    trips_b = simulate_plan(baseline, base_seed=seed_val)
    trips_s = simulate_plan(smarter,  base_seed=seed_val)
    det = detect_all(baseline, trips_b)
    recommended = build_recommended_plan(baseline, trips_b, det["missed_connections"])
    trips_r = simulate_plan(recommended, base_seed=seed_val)
    m_b = compute_metrics(baseline,     trips_b, seed_val)
    m_s = compute_metrics(smarter,      trips_s, seed_val)
    m_r = compute_metrics(recommended,  trips_r, seed_val)
    val_b = validate(baseline,     trips_b)
    val_s = validate(smarter,      trips_s)
    val_r = validate(recommended,  trips_r)
    ts    = tradeoff_summary(recommended.actions_applied)
    return recommended, trips_b, trips_s, trips_r, m_b, m_s, m_r, val_b, val_s, val_r, ts, det

with st.spinner("Computing recommendations…"):
    recommended, trips_b, trips_s, trips_r, m_b, m_s, m_r, val_b, val_s, val_r, ts, det = \
        _get_recommendation(int(seed))

# ── Validation badges ──────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns(3)
with col_a: validation_badge("Naive Baseline",          val_b)
with col_b: validation_badge("Smarter Baseline",        val_s)
with col_c: validation_badge("RoutePulse Recommendation", val_r)

st.divider()

# ── Comparison table ───────────────────────────────────────────────────────────
st.subheader(f"📊 Plan Comparison (seed {seed})")
metrics_defs = [
    ("ETA MAE (min)",         "eta_mae_minutes",      False),
    ("ETA Calibration",       "eta_calibration",      True),
    ("Overcrowding Events",   "overcrowding_events",  False),
    ("Unmet Demand",          "total_unmet_demand",   False),
    ("Missed Connections",    "missed_connections",   False),
    ("Avg Wait (min)",        "average_wait_minutes", False),
    ("Fleet Utilisation",     "fleet_utilisation",    True),
]

def _delta_fmt(v, base):
    d = v - base
    pct = d / base * 100 if base != 0 else 0
    return f"{d:+.2f} ({pct:+.1f}%)"

rows = []
for label, key, hib in metrics_defs:
    bv = m_b[key]; sv = m_s[key]; rv = m_r[key]
    better = ((rv < bv) if not hib else (rv > bv)) and bv != rv
    rows.append({
        "Metric": label,
        "Naive Baseline":   round(bv, 3) if isinstance(bv, float) else bv,
        "Smarter Baseline": round(sv, 3) if isinstance(sv, float) else sv,
        "RoutePulse":       round(rv, 3) if isinstance(rv, float) else rv,
        "Δ vs Naive":       _delta_fmt(rv, bv),
        "Better?":          "✓" if better else ("=" if rv == bv else "✗"),
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ── Radar chart ────────────────────────────────────────────────────────────────
st.subheader("Multi-dimension Radar Comparison")
categories = ["Low ETA Error", "High Calibration", "Low Overcrowding",
              "Low Unmet Demand", "Low Missed Conns", "High Fleet Util"]
raw = {
    "Naive":      [m_b["eta_mae_minutes"], m_b["eta_calibration"], m_b["overcrowding_events"],
                   m_b["total_unmet_demand"], m_b["missed_connections"], m_b["fleet_utilisation"]],
    "Smarter":    [m_s["eta_mae_minutes"], m_s["eta_calibration"], m_s["overcrowding_events"],
                   m_s["total_unmet_demand"], m_s["missed_connections"], m_s["fleet_utilisation"]],
    "RoutePulse": [m_r["eta_mae_minutes"], m_r["eta_calibration"], m_r["overcrowding_events"],
                   m_r["total_unmet_demand"], m_r["missed_connections"], m_r["fleet_utilisation"]],
}
inverts = [True, False, True, True, True, False]
mins_ = [min(raw[k][i] for k in raw) for i in range(6)]
maxs_ = [max(raw[k][i] for k in raw) for i in range(6)]

def _norm(v, mn, mx, inv):
    if mx == mn: return 0.5
    n = (v - mn) / (mx - mn)
    return 1 - n if inv else n

colors = {"Naive": "#4a5568", "Smarter": "#63b3ed", "RoutePulse": "#68d391"}
fig_radar = go.Figure()
for plan_name, vals in raw.items():
    norm = [_norm(v, mins_[i], maxs_[i], inverts[i]) for i, v in enumerate(vals)]
    norm.append(norm[0])
    fig_radar.add_trace(go.Scatterpolar(r=norm, theta=categories + [categories[0]],
        fill="toself", fillcolor=colors[plan_name] + "22",
        line=dict(color=colors[plan_name], width=2), name=plan_name))
fig_radar.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
    polar=dict(bgcolor="rgba(0,0,0,0)",
        radialaxis=dict(visible=True, range=[0,1], showticklabels=False,
                        gridcolor="rgba(99,179,237,0.1)"),
        angularaxis=dict(gridcolor="rgba(99,179,237,0.1)")),
    height=380, margin=dict(l=30,r=30,t=30,b=30),
    legend=dict(orientation="h", yanchor="bottom", y=-0.2))
st.plotly_chart(fig_radar, use_container_width=True)

st.divider()

# ── Trade-off summary ──────────────────────────────────────────────────────────
st.subheader("⚖️ Trade-off Summary")
tc1, tc2, tc3 = st.columns(3)
tc1.metric("Vehicle Upgrades",  ts["vehicle_upgrades"],  help="Small → Large bus swaps")
tc2.metric("Extra Trips",       ts["extra_trips"],        help="Additional departures inserted")
tc3.metric("Departure Nudges",  ts["departure_nudges"],   help="Departure times shifted")
st.info(
    f"**Fleet cost impact:** {ts['fleet_cost_impact']}  \n"
    f"**Crowding reduction:** {ts['crowding_reduction']}  \n"
    f"**Connection improvement:** {ts['connection_improvement']}"
)

# ── Action list ────────────────────────────────────────────────────────────────
st.subheader("📋 Recommended Actions")
actions = recommended.actions_applied
if not actions:
    st.success("No actions needed — baseline is already within tolerance for this seed.")
else:
    icons = {"vehicle_swap": "🚌", "extra_trip": "➕", "departure_nudge": "⏰"}
    for i, action in enumerate(actions, 1):
        icon = icons.get(action.action_type, "•")
        with st.expander(f"{icon} Action {i}: {action.description}", expanded=(i <= 2)):
            col_x, col_y = st.columns(2)
            col_x.markdown(f"**Cost:** {action.cost_label}")
            col_y.markdown(f"**Benefit:** {action.benefit_label}")
            if action.action_type == "departure_nudge":
                st.markdown(f"**Time shift:** {action.time_shift_minutes:+.0f} min")
