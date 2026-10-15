"""
Page 4 — Plan Recommendations
Before/after comparison, trade-off explorer, and action explanations.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Recommendations — RoutePulse", page_icon="🔧", layout="wide")

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


def fmt_time(m):
    h, mn = divmod(int(m), 60)
    return f"{h:02d}:{mn:02d}"


@st.cache_resource
def load_data():
    from routepulse.data_gen import build_campus, build_baseline_plan, build_smarter_baseline_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    smarter  = build_smarter_baseline_plan(stops=stops, routes=routes, vehicles=vehicles)
    return stops, routes, vehicles, departures, baseline, smarter


@st.cache_data
def get_recommendation(seed):
    from routepulse.data_gen import build_campus, build_baseline_plan, build_smarter_baseline_plan
    from routepulse.simulator import simulate_plan
    from routepulse.detector import detect_all
    from routepulse.optimizer import build_recommended_plan, tradeoff_summary
    from routepulse.evaluator import compute_metrics, comparison_table, improvement_table
    from routepulse.validator import validate

    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    smarter  = build_smarter_baseline_plan(stops=stops, routes=routes, vehicles=vehicles)

    trips_b = simulate_plan(baseline, base_seed=seed)
    trips_s = simulate_plan(smarter, base_seed=seed)
    det = detect_all(baseline, trips_b)

    recommended = build_recommended_plan(baseline, trips_b, det["missed_connections"])
    trips_r = simulate_plan(recommended, base_seed=seed)

    m_b = compute_metrics(baseline, trips_b, seed)
    m_s = compute_metrics(smarter, trips_s, seed)
    m_r = compute_metrics(recommended, trips_r, seed)

    val_b = validate(baseline, trips_b)
    val_s = validate(smarter, trips_s)
    val_r = validate(recommended, trips_r)

    ts = tradeoff_summary(recommended.actions_applied)

    return (
        baseline, smarter, recommended,
        trips_b, trips_s, trips_r,
        m_b, m_s, m_r,
        val_b, val_s, val_r,
        recommended.actions_applied, ts, det,
    )


stops, routes, vehicles, departures, baseline, smarter = load_data()

st.title("🔧 Plan Recommendations")
st.caption("Feasible schedule adjustments — validated against all hard constraints before display")

seed = st.sidebar.number_input("Simulation seed", value=42, min_value=42, max_value=52, step=1)

with st.spinner("Generating recommendations..."):
    (
        plan_b, plan_s, plan_r,
        trips_b, trips_s, trips_r,
        m_b, m_s, m_r,
        val_b, val_s, val_r,
        actions, ts, det,
    ) = get_recommendation(int(seed))

# ── Validation badge ───────────────────────────────────────────────────────────
col_a, col_b, col_c = st.columns(3)
for col, plan, val, label in [
    (col_a, plan_b, val_b, "Naive Baseline"),
    (col_b, plan_s, val_s, "Smarter Baseline"),
    (col_c, plan_r, val_r, "RoutePulse Recommendation"),
]:
    with col:
        ok = val.passed
        color = "#276749" if ok else "#742a2a"
        bg = "rgba(39,103,73,0.2)" if ok else "rgba(116,42,42,0.2)"
        icon = "✅ VALID" if ok else f"❌ {val.n_violations} violations"
        st.markdown(
            f'<div style="background:{bg};border:1px solid {color};border-radius:10px;'
            f'padding:12px;text-align:center">'
            f'<b style="font-size:13px;color:#a0aec0">{label}</b><br>'
            f'<span style="font-size:20px;font-weight:700;color:{"#68d391" if ok else "#fc8181"}">{icon}</span>'
            f'</div>', unsafe_allow_html=True,
        )

st.divider()

# ── Comparison table ───────────────────────────────────────────────────────────
st.subheader("📊 Plan Comparison (seed {})".format(seed))

metrics_labels = [
    ("ETA MAE (min)", "eta_mae_minutes", False),
    ("ETA Calibration", "eta_calibration", True),
    ("Overcrowding Events", "overcrowding_events", False),
    ("Unmet Demand", "total_unmet_demand", False),
    ("Missed Connections", "missed_connections", False),
    ("Avg Wait (min)", "average_wait_minutes", False),
    ("Fleet Utilisation", "fleet_utilisation", True),
]

rows = []
for label, key, higher_is_better in metrics_labels:
    bv = m_b[key]
    sv = m_s[key]
    rv = m_r[key]

    def delta_fmt(v, base):
        d = v - base
        pct = d / base * 100 if base != 0 else 0
        return f"{d:+.2f} ({pct:+.1f}%)"

    rows.append({
        "Metric": label,
        "Naive Baseline": round(bv, 3) if isinstance(bv, float) else bv,
        "Smarter Baseline": round(sv, 3) if isinstance(sv, float) else sv,
        "RoutePulse": round(rv, 3) if isinstance(rv, float) else rv,
        "Δ vs Naive": delta_fmt(rv, bv),
        "Better?": "✓" if ((rv < bv) != higher_is_better if bv != rv else False) or ((rv > bv) and higher_is_better) else ("=" if rv == bv else "✗"),
    })

df_cmp = pd.DataFrame(rows)
st.dataframe(df_cmp, hide_index=True, use_container_width=True)

# ── Radar chart ────────────────────────────────────────────────────────────────
st.subheader("Radar: Multi-dimension Comparison")

import numpy as np

categories = ["Low ETA Error", "High Calibration", "Low Overcrowding", "Low Unmet Demand", "Low Missed Conns", "High Fleet Util"]

def normalise(val, min_v, max_v, invert=False):
    if max_v == min_v:
        return 0.5
    n = (val - min_v) / (max_v - min_v)
    return 1 - n if invert else n

# Compute raw
raw = {
    "Naive": [m_b["eta_mae_minutes"], m_b["eta_calibration"], m_b["overcrowding_events"], m_b["total_unmet_demand"], m_b["missed_connections"], m_b["fleet_utilisation"]],
    "Smarter": [m_s["eta_mae_minutes"], m_s["eta_calibration"], m_s["overcrowding_events"], m_s["total_unmet_demand"], m_s["missed_connections"], m_s["fleet_utilisation"]],
    "RoutePulse": [m_r["eta_mae_minutes"], m_r["eta_calibration"], m_r["overcrowding_events"], m_r["total_unmet_demand"], m_r["missed_connections"], m_r["fleet_utilisation"]],
}
inverts = [True, False, True, True, True, False]
mins = [min(raw[k][i] for k in raw) for i in range(6)]
maxs = [max(raw[k][i] for k in raw) for i in range(6)]

fig_radar = go.Figure()
colors = {"Naive": "#4a5568", "Smarter": "#63b3ed", "RoutePulse": "#68d391"}
for plan_name, vals in raw.items():
    norm = [normalise(v, mins[i], maxs[i], inverts[i]) for i, v in enumerate(vals)]
    norm.append(norm[0])
    fig_radar.add_trace(go.Scatterpolar(
        r=norm,
        theta=categories + [categories[0]],
        fill="toself",
        fillcolor=colors[plan_name].replace(")", ",0.15)").replace("rgb", "rgba") if "rgb" in colors[plan_name] else colors[plan_name] + "26",
        line=dict(color=colors[plan_name], width=2),
        name=plan_name,
    ))

fig_radar.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    polar=dict(
        bgcolor="rgba(0,0,0,0)",
        radialaxis=dict(visible=True, range=[0, 1], showticklabels=False, gridcolor="rgba(99,179,237,0.1)"),
        angularaxis=dict(gridcolor="rgba(99,179,237,0.1)"),
    ),
    height=380,
    margin=dict(l=30, r=30, t=30, b=30),
    legend=dict(orientation="h", yanchor="bottom", y=-0.15),
)
st.plotly_chart(fig_radar, use_container_width=True)

st.divider()

# ── Trade-off summary ──────────────────────────────────────────────────────────
st.subheader("⚖️ Trade-off Summary")

tc1, tc2, tc3 = st.columns(3)
tc1.metric("Vehicle Upgrades", ts["vehicle_upgrades"], help="Small → Large bus swaps")
tc2.metric("Extra Trips", ts["extra_trips"], help="Additional departures inserted")
tc3.metric("Departure Nudges", ts["departure_nudges"], help="Departure times shifted to fix connections")

st.info(
    f"**Fleet cost impact:** {ts['fleet_cost_impact']}  \n"
    f"**Crowding reduction:** {ts['crowding_reduction']}  \n"
    f"**Connection improvement:** {ts['connection_improvement']}"
)

# ── Action list ────────────────────────────────────────────────────────────────
st.subheader("📋 Recommended Actions")

if not actions:
    st.success("No actions needed — the baseline plan is already optimal for this seed.")
else:
    action_icons = {
        "vehicle_swap": "🚌",
        "extra_trip": "➕",
        "departure_nudge": "⏰",
    }
    for i, action in enumerate(actions, 1):
        icon = action_icons.get(action.action_type, "•")
        with st.expander(f"{icon} Action {i}: {action.description}", expanded=(i <= 3)):
            col_x, col_y = st.columns(2)
            col_x.markdown(f"**Cost:** {action.cost_label}")
            col_y.markdown(f"**Benefit:** {action.benefit_label}")
            if action.action_type == "departure_nudge":
                st.markdown(f"**Time shift:** {action.time_shift_minutes:+.0f} min")
