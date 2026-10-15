"""
Page 2 — Arrival Estimates
Kalman-filter ETA with confidence intervals and calibration check.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

st.set_page_config(page_title="Arrivals — RoutePulse", page_icon="⏱️", layout="wide")

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
def load_campus():
    from routepulse.data_gen import build_campus, build_baseline_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    return stops, routes, vehicles, departures, baseline


@st.cache_data
def get_trips(seed):
    from routepulse.data_gen import build_campus, build_baseline_plan
    from routepulse.simulator import simulate_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    return simulate_plan(baseline, base_seed=seed)


def fmt_time(m):
    h, mn = divmod(int(m), 60)
    return f"{h:02d}:{mn:02d}"


st.title("⏱️ Arrival Estimates")
st.caption("Kalman-filtered ETA with 90% confidence intervals")

stops, routes, vehicles, departures, baseline = load_campus()

# Controls
col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    route_names = {r.name: r for r in routes.values()}
    sel_route_name = st.selectbox("Route", list(route_names.keys()))
    sel_route = route_names[sel_route_name]

with col2:
    # Filter departures for selected route in time range
    route_deps = [d for d in departures if d.route.route_id == sel_route.route_id]
    dep_labels = [f"{fmt_time(d.departure_time)} — {d.departure_id}" for d in route_deps]
    sel_dep_idx = st.selectbox("Departure", range(len(dep_labels)), format_func=lambda i: dep_labels[i])
    sel_dep = route_deps[sel_dep_idx]

with col3:
    seed = st.number_input("Seed", value=42, min_value=42, max_value=52, step=1)

trips = get_trips(int(seed))

# Find the simulated trip for selected departure
trip = next((t for t in trips if t.departure.departure_id == sel_dep.departure_id), None)

if trip is None:
    st.warning("This trip was cancelled (vehicle breakdown). Select a different departure.")
    st.stop()

# Split: treat first half as observed, estimate second half
n = len(trip.stop_events)
split = max(1, n // 2)
observed = trip.stop_events[:split]
future_events = trip.stop_events[split:]

from routepulse.estimator import estimate_etas, check_eta_calibration
estimates = estimate_etas(sel_dep, observed)
future_actuals = {ev.stop.stop_id: ev.actual_arrival for ev in future_events}
cal = check_eta_calibration(estimates, future_actuals)

# ── Metrics ────────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("ETA MAE", f"{cal['mae_minutes']:.2f} min")
c2.metric("Calibration (90% CI)", f"{cal['calibration']:.1%}")
c3.metric("Observed Stops", split)
c4.metric("Estimated Stops", len(estimates))

st.divider()

# ── ETA chart ──────────────────────────────────────────────────────────────────
st.subheader("Stop-by-Stop Arrival Timeline")

fig = go.Figure()

# Observed (actual)
obs_names = [ev.stop.name for ev in observed]
obs_actual = [ev.actual_arrival for ev in observed]
obs_sched = [ev.scheduled_arrival for ev in observed]

fig.add_trace(go.Scatter(
    x=obs_names, y=obs_actual,
    mode="markers+lines",
    name="Observed (actual)",
    marker=dict(color="#63b3ed", size=10, symbol="circle"),
    line=dict(color="#63b3ed", width=2),
))
fig.add_trace(go.Scatter(
    x=obs_names, y=obs_sched,
    mode="markers+lines",
    name="Scheduled",
    marker=dict(color="#4a5568", size=7, symbol="diamond"),
    line=dict(color="#4a5568", width=1.5, dash="dot"),
))

# Estimates (future)
if estimates:
    est_names = [e.stop.name for e in estimates]
    est_vals  = [e.estimated_arrival for e in estimates]
    est_hi    = [e.upper_bound for e in estimates]
    est_lo    = [e.lower_bound for e in estimates]

    # CI band
    fig.add_trace(go.Scatter(
        x=est_names + est_names[::-1],
        y=est_hi + est_lo[::-1],
        fill="toself",
        fillcolor="rgba(246,173,85,0.12)",
        line=dict(color="rgba(0,0,0,0)"),
        name="90% CI",
        showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=est_names, y=est_vals,
        mode="markers+lines",
        name="ETA estimate",
        marker=dict(color="#f6ad55", size=10, symbol="circle-open"),
        line=dict(color="#f6ad55", width=2, dash="dash"),
    ))
    # Actual future (for calibration viz)
    fut_actual = [future_actuals.get(e.stop.stop_id) for e in estimates]
    fig.add_trace(go.Scatter(
        x=est_names, y=fut_actual,
        mode="markers",
        name="Actual (future, revealed)",
        marker=dict(color="#68d391", size=10, symbol="x"),
    ))

fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=380,
    margin=dict(l=0, r=0, t=20, b=0),
    xaxis=dict(title="Stop", showgrid=False),
    yaxis=dict(title="Time (min since midnight)", showgrid=True, gridcolor="rgba(99,179,237,0.08)"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig, use_container_width=True)

# ── Delay propagation chart ────────────────────────────────────────────────────
st.subheader("Delay Propagation Along Route")
all_names = [ev.stop.name for ev in trip.stop_events]
all_delays = [ev.delay for ev in trip.stop_events]
colors = ["#63b3ed" if i < split else "#f6ad55" for i in range(len(all_names))]

fig2 = go.Figure(go.Bar(
    x=all_names, y=all_delays,
    marker_color=colors,
    text=[f"{d:+.1f} min" for d in all_delays],
    textposition="outside",
))
fig2.add_hline(y=0, line_dash="dot", line_color="#4a5568")
fig2.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=260,
    margin=dict(l=0, r=0, t=20, b=0),
    xaxis=dict(title="Stop", showgrid=False),
    yaxis=dict(title="Delay (min)", showgrid=True, gridcolor="rgba(99,179,237,0.08)"),
)
st.plotly_chart(fig2, use_container_width=True)

# ── Detail table ───────────────────────────────────────────────────────────────
st.subheader("Stop-by-Stop Detail")
rows = []
for ev in trip.stop_events:
    eta_row = next((e for e in estimates if e.stop.stop_id == ev.stop.stop_id), None)
    rows.append({
        "Stop": ev.stop.name,
        "Scheduled": fmt_time(ev.scheduled_arrival),
        "Actual": fmt_time(ev.actual_arrival),
        "Delay (min)": f"{ev.delay:+.1f}",
        "ETA Estimate": fmt_time(eta_row.estimated_arrival) if eta_row else "—",
        "± CI (min)": f"±{eta_row.uncertainty_minutes:.1f}" if eta_row else "—",
        "In CI?": ("✓" if eta_row and eta_row.lower_bound <= ev.actual_arrival <= eta_row.upper_bound else "✗") if eta_row else "—",
        "Demand": ev.demand_at_stop,
        "Boarded": ev.boarded,
        "Unmet": ev.unmet_demand,
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.caption("""
**Methodology**: A 1D Kalman filter tracks delay state along the route.
Process noise = 0.25 min/stop (delay uncertainty grows). Observation noise = 0.3 min.
CI half-width = z₀.₀₅ × predicted std. Calibration = fraction of future stops where
actual arrival fell inside the stated 90% CI.
""")
