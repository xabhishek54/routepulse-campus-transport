"""
Page 2 — Arrival Estimates
Kalman ETA with confidence intervals, delay propagation, and calibration.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from app.utils import inject_css, load_campus, fmt_time
from routepulse.estimator import estimate_etas, check_eta_calibration
from routepulse.simulator import simulate_plan
from routepulse.config import ETA_CI_PCT, SEED

inject_css()

stops, routes, vehicles, departures, baseline, smarter = load_campus()

st.title("⏱️ Arrival Estimates")
st.caption(f"Kalman-filtered ETA with {ETA_CI_PCT:.0f}% confidence intervals")

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    route_names = {r.name: r for r in routes.values()}
    sel_route = route_names[st.selectbox("Route", list(route_names.keys()))]
with col2:
    route_deps = [d for d in departures if d.route.route_id == sel_route.route_id]
    dep_labels = [f"{fmt_time(d.departure_time)} — {d.departure_id}" for d in route_deps]
    sel_dep = route_deps[st.selectbox("Departure", range(len(dep_labels)),
                                       format_func=lambda i: dep_labels[i])]
with col3:
    seed = st.number_input("Seed", value=SEED, min_value=SEED, max_value=SEED + 10, step=1)

@st.cache_data(show_spinner="Simulating…")
def _get_trips(seed_val):
    return simulate_plan(baseline, base_seed=seed_val)

trips = _get_trips(int(seed))
trip = next((t for t in trips if t.departure.departure_id == sel_dep.departure_id), None)

if trip is None:
    st.warning("This trip was cancelled (vehicle breakdown). Select another departure.")
    st.stop()

n = len(trip.stop_events)
split = max(1, n // 2)
observed = trip.stop_events[:split]
future_events = trip.stop_events[split:]

estimates = estimate_etas(sel_dep, observed, confidence_pct=ETA_CI_PCT)
future_actuals = {ev.stop.stop_id: ev.actual_arrival for ev in future_events}
cal = check_eta_calibration(estimates, future_actuals)

# ── Metrics ────────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("ETA MAE", f"{cal['mae_minutes']:.2f} min",
          help="Mean absolute error of point estimates vs actual arrivals")
c2.metric(f"Calibration ({ETA_CI_PCT:.0f}% CI)",
          f"{cal['calibration']:.1%}",
          help="Fraction of future stops where actual arrival fell inside stated CI")
c3.metric("Observed Stops", split)
c4.metric("Estimated Stops", len(estimates))

st.divider()

# ── Timeline chart ─────────────────────────────────────────────────────────────
st.subheader("Stop-by-Stop Arrival Timeline")
fig = go.Figure()

obs_names  = [ev.stop.name for ev in observed]
obs_actual = [ev.actual_arrival for ev in observed]
obs_sched  = [ev.scheduled_arrival for ev in observed]

fig.add_trace(go.Scatter(x=obs_names, y=obs_sched, mode="markers+lines",
    name="Scheduled", marker=dict(color="#4a5568", size=7, symbol="diamond"),
    line=dict(color="#4a5568", width=1.5, dash="dot")))
fig.add_trace(go.Scatter(x=obs_names, y=obs_actual, mode="markers+lines",
    name="Observed (actual)", marker=dict(color="#63b3ed", size=10),
    line=dict(color="#63b3ed", width=2)))

if estimates:
    est_names = [e.stop.name for e in estimates]
    est_vals  = [e.estimated_arrival for e in estimates]
    fig.add_trace(go.Scatter(
        x=est_names + est_names[::-1],
        y=[e.upper_bound for e in estimates] + [e.lower_bound for e in estimates][::-1],
        fill="toself", fillcolor="rgba(246,173,85,0.12)",
        line=dict(color="rgba(0,0,0,0)"), name=f"{ETA_CI_PCT:.0f}% CI"))
    fig.add_trace(go.Scatter(x=est_names, y=est_vals, mode="markers+lines",
        name="ETA estimate", marker=dict(color="#f6ad55", size=10, symbol="circle-open"),
        line=dict(color="#f6ad55", width=2, dash="dash")))
    fut_actual = [future_actuals.get(e.stop.stop_id) for e in estimates]
    fig.add_trace(go.Scatter(x=est_names, y=fut_actual, mode="markers",
        name="Actual (revealed)", marker=dict(color="#68d391", size=10, symbol="x")))

fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)", height=380, margin=dict(l=0, r=0, t=20, b=0),
    xaxis=dict(title="Stop", showgrid=False),
    yaxis=dict(title="Time (min since midnight)", showgrid=True, gridcolor="rgba(99,179,237,0.08)"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02))
st.plotly_chart(fig, use_container_width=True)

# ── Delay chart ────────────────────────────────────────────────────────────────
st.subheader("Delay Propagation Along Route")
all_names  = [ev.stop.name for ev in trip.stop_events]
all_delays = [ev.delay for ev in trip.stop_events]
colors = ["#63b3ed" if i < split else "#f6ad55" for i in range(len(all_names))]
fig2 = go.Figure(go.Bar(x=all_names, y=all_delays, marker_color=colors,
    text=[f"{d:+.1f}" for d in all_delays], textposition="outside"))
fig2.add_hline(y=0, line_dash="dot", line_color="#4a5568")
fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)", height=250, margin=dict(l=0, r=0, t=20, b=0),
    xaxis_title="Stop", yaxis_title="Delay (min)")
st.plotly_chart(fig2, use_container_width=True)
st.caption("Blue = observed stops. Orange = estimated stops (Kalman prediction).")

# ── Detail table ───────────────────────────────────────────────────────────────
st.subheader("Stop-by-Stop Detail")
rows = []
for ev in trip.stop_events:
    eta_row = next((e for e in estimates if e.stop.stop_id == ev.stop.stop_id), None)
    in_ci = (eta_row and eta_row.lower_bound <= ev.actual_arrival <= eta_row.upper_bound)
    rows.append({
        "Stop": ev.stop.name,
        "Scheduled": fmt_time(ev.scheduled_arrival),
        "Actual": fmt_time(ev.actual_arrival),
        "Delay (min)": f"{ev.delay:+.1f}",
        "ETA Estimate": fmt_time(eta_row.estimated_arrival) if eta_row else "—",
        f"± {ETA_CI_PCT:.0f}% CI": f"±{eta_row.uncertainty_minutes:.1f}" if eta_row else "—",
        "In CI?": ("✓" if in_ci else "✗") if eta_row else "—",
        "Demand": ev.demand_at_stop,
        "Boarded": ev.boarded,
        "Unmet": ev.unmet_demand,
    })
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.caption(
    f"**Methodology**: 1D Kalman filter. Process noise Q = {0.25}² min²/stop. "
    f"Observation noise R = {0.3}² min². CI = z(α/2) × √(P + n·Q). "
    f"Calibration target: {ETA_CI_PCT:.0f}% of future arrivals inside CI."
)
