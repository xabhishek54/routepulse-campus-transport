"""
Page: When will my bus arrive?

Shows real-time ETA estimates with 90% confidence intervals for a selected trip.
Explains clearly: what the CI means, what calibration means.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from app.utils import inject_css, load_campus, get_simulation, page_header, fmt_time
from app.utils import ACCENT, SUCCESS, WARNING, DANGER, NEUTRAL

st.set_page_config(page_title="Arrivals — RoutePulse", page_icon="⬡", layout="wide")
inject_css()
page_header(
    "When will my bus arrive?",
    "Kalman-filter ETA estimates with 90% confidence intervals · Calibration measured independently"
)

# ─── Load data ─────────────────────────────────────────────────────────────────
stops, routes, vehicles, departures, naive, smarter = load_campus()
seed = st.session_state.get("selected_seed", 42)
plan, trips = get_simulation("baseline_naive", seed)

if not trips:
    st.error("No trips returned."); st.stop()

# ─── Selector ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Select a trip")
    route_choice = st.selectbox(
        "Route",
        options=list(routes.keys()),
        format_func=lambda rid: routes[rid].name,
    )
    route_trips = [t for t in trips if t.departure.route.route_id == route_choice]
    if not route_trips:
        st.warning("No trips for this route."); st.stop()

    trip_choice_idx = st.selectbox(
        "Departure time",
        options=list(range(len(route_trips))),
        format_func=lambda i: fmt_time(route_trips[i].departure.departure_time),
    )

selected_trip = route_trips[trip_choice_idx]
dep = selected_trip.departure
route = dep.route
n_stops = len(selected_trip.stop_events)
split = max(1, n_stops // 2)  # use first half as 'observed', estimate second half

# ─── ETA estimation ────────────────────────────────────────────────────────────
from routepulse.estimator import estimate_etas, evaluate_eta_over_trips

observed = selected_trip.stop_events[:split]
etas     = estimate_etas(dep, observed)

# ─── Metrics ──────────────────────────────────────────────────────────────────
# Compute calibration over ALL trips (not just this one — that would be misleading)
all_eta_result = evaluate_eta_over_trips(trips)
cal_pct   = all_eta_result["eta_calibration"]
cal_gap   = all_eta_result["eta_calibration_gap_pp"]
mae       = all_eta_result["eta_mae_minutes"]
n_eval    = all_eta_result["n_evaluated"]

cal_color = SUCCESS if abs(cal_gap) <= 10 else (WARNING if abs(cal_gap) <= 20 else DANGER)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stops observed so far", f"{split} / {n_stops}")
c2.metric(
    "ETA accuracy (MAE)",
    f"{mae:.1f} min",
    help="Mean absolute error between ETA estimate and actual arrival, measured across all trips and both seeds"
)
c3.metric(
    "CI calibration (all trips)",
    f"{cal_pct:.0%}",
    help=f"Fraction of future arrivals that actually fell inside the 90% confidence interval. Target: 90%. Gap from target: {cal_gap:+.1f} percentage points. Measured over {n_eval:,} stop-pairs."
)
c4.metric(
    "Calibration gap",
    f"{cal_gap:+.1f} pp",
    help="Gap from the 90% target. Positive = overconfident (CI too narrow). Within ±10pp is considered well-calibrated."
)

# ─── ETA chart ────────────────────────────────────────────────────────────────
st.markdown("### Arrival window for each upcoming stop")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>"
    f"Trip: {route.name} departing {fmt_time(dep.departure_time)} · "
    f"Showing {split} observed stops + {len(etas)} estimated ahead · "
    f"Shaded band = 90% confidence interval</p>",
    unsafe_allow_html=True
)

# Build a unified timeline: observed (actual) + estimated (future)
fig = go.Figure()

# Observed actuals
obs_stops  = [ev.stop.name for ev in observed]
obs_actual = [ev.actual_arrival for ev in observed]
obs_sched  = [ev.scheduled_arrival for ev in observed]

fig.add_trace(go.Scatter(
    x=obs_stops, y=obs_actual,
    mode="lines+markers",
    name="Actual arrival (observed)",
    line=dict(color=SUCCESS, width=2),
    marker=dict(size=9, color=SUCCESS),
    hovertemplate="<b>%{x}</b><br>Actual: %{customdata}<extra></extra>",
    customdata=[fmt_time(a) for a in obs_actual],
))
fig.add_trace(go.Scatter(
    x=obs_stops, y=obs_sched,
    mode="lines",
    name="Scheduled",
    line=dict(color=NEUTRAL, width=1.5, dash="dot"),
    hovertemplate="<b>%{x}</b><br>Scheduled: %{customdata}<extra></extra>",
    customdata=[fmt_time(s) for s in obs_sched],
))

# ETA estimates with CI bands
if etas:
    eta_stops = [e.stop.name for e in etas]
    eta_means  = [e.estimated_arrival for e in etas]
    eta_lowers = [e.lower_bound for e in etas]
    eta_uppers = [e.upper_bound for e in etas]
    eta_actuals = [
        next((ev.actual_arrival for ev in selected_trip.stop_events if ev.stop.stop_id == e.stop.stop_id), None)
        for e in etas
    ]

    # CI band
    fig.add_trace(go.Scatter(
        x=eta_stops + eta_stops[::-1],
        y=eta_uppers + eta_lowers[::-1],
        fill="toself",
        fillcolor=f"rgba(96,165,250,0.12)",
        line=dict(color="rgba(96,165,250,0)"),
        showlegend=True,
        name="90% confidence interval",
        hoverinfo="skip",
    ))
    # Estimated line
    fig.add_trace(go.Scatter(
        x=eta_stops, y=eta_means,
        mode="lines+markers",
        name="ETA estimate",
        line=dict(color=ACCENT, width=2, dash="dash"),
        marker=dict(size=9, color=ACCENT),
        hovertemplate=(
            "<b>%{x}</b><br>"
            "ETA: %{customdata[0]}<br>"
            "90% window: %{customdata[1]} – %{customdata[2]}"
            "<extra></extra>"
        ),
        customdata=list(zip(
            [fmt_time(m) for m in eta_means],
            [fmt_time(l) for l in eta_lowers],
            [fmt_time(u) for u in eta_uppers],
        )),
    ))
    # Actual (for comparison)
    valid_etas = [(s, a) for s, a in zip(eta_stops, eta_actuals) if a is not None]
    if valid_etas:
        fig.add_trace(go.Scatter(
            x=[s for s, _ in valid_etas],
            y=[a for _, a in valid_etas],
            mode="markers",
            name="Actual (revealed)",
            marker=dict(size=10, color=WARNING, symbol="diamond"),
            hovertemplate="<b>%{x}</b><br>Actual: %{customdata}<extra></extra>",
            customdata=[fmt_time(a) for _, a in valid_etas],
        ))

# Vertical separator
if obs_stops and etas:
    divider_x = obs_stops[-1]
    last_obs_y = obs_actual[-1]
    fig.add_vline(x=len(obs_stops) - 0.5, line_dash="dash", line_color=NEUTRAL,
                  annotation_text="Now", annotation_font_color=NEUTRAL, annotation_font_size=11)

fig.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(title="Stop", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
    yaxis=dict(
        title="Time of day",
        color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)",
        ticktext=[fmt_time(m) for m in range(480, 1201, 30)],
        tickvals=list(range(480, 1201, 30)),
    ),
    font=dict(color=NEUTRAL),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=NEUTRAL)),
    height=400, margin=dict(l=10, r=20, t=20, b=30),
)
st.plotly_chart(fig, use_container_width=True)

# ─── What does this mean? ─────────────────────────────────────────────────────
st.markdown("### Understanding this chart")
st.markdown(f"""
<div style='color:{NEUTRAL};font-size:13px;line-height:1.7'>
<b style='color:#e2e8f0'>Green line (observed)</b> — Where this bus actually was. We've seen these stops already.<br>
<b style='color:{ACCENT}'>Blue dashed line (ETA estimate)</b> — Our prediction for stops the bus hasn't reached yet.<br>
<b style='color:rgba(96,165,250,0.6)'>Shaded band (90% CI)</b> — We're 90% confident the bus will arrive within this window.<br>
<b style='color:{WARNING}'>Yellow diamonds (actual)</b> — Where the bus actually arrived (shown after the fact).<br><br>

<b style='color:#e2e8f0'>ETA calibration = {cal_pct:.0%} (target 90%)</b><br>
This means {cal_pct:.0%} of actual arrivals fell within the shaded band, measured over {n_eval:,} future stop predictions.
{"Well calibrated — within ±10pp of target." if abs(cal_gap) <= 10 else f"Gap from target: {cal_gap:+.1f} percentage points. {'Slightly overconfident (band too narrow).' if cal_gap < 0 else 'Slightly underconfident (band too wide).'}"}<br><br>

The Kalman filter starts with an initial delay estimate and updates it at each observed stop.
Uncertainty grows by {1.2} min (std) per stop ahead — so predictions further away have wider bands.
</div>
""", unsafe_allow_html=True)
