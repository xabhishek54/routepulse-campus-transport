"""
Page 3 — Violation Detection
Constraint validator + overcrowding + missed connections + load heatmap.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from app.utils import inject_css, load_campus, fmt_time, validation_badge
from routepulse.simulator import simulate_plan
from routepulse.detector import detect_all
from routepulse.validator import validate
from routepulse.config import SEED, MIN_HEADWAY, MAX_WAIT_FOR_CONNECTION

inject_css()

stops, routes, vehicles, departures, baseline, smarter = load_campus()

st.title("⚠️ Violation Detection")
st.caption("Independent constraint checker · overcrowding · missed connections")

seed = st.sidebar.number_input("Simulation seed", value=SEED, min_value=SEED,
                                max_value=SEED + 10, step=1)

@st.cache_data(show_spinner="Detecting violations…")
def _get_analysis(seed_val):
    trips = simulate_plan(baseline, base_seed=seed_val)
    det = detect_all(baseline, trips)
    val_report = validate(baseline, trips)
    return trips, det, val_report

trips, det, val_report = _get_analysis(int(seed))

# ── Headline metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Overcrowding Events", det["summary"]["overcrowding_events"],
          delta="⚠ critical" if det["summary"]["overcrowding_events"] > 0 else None,
          delta_color="inverse")
c2.metric("Schedule Conflicts", det["summary"]["schedule_conflicts"],
          help=f"Headway < {MIN_HEADWAY:.0f} min between same-route departures")
c3.metric("Missed Connections", det["summary"]["missed_connections"],
          help=f"Extra wait > {MAX_WAIT_FOR_CONNECTION:.0f} min at transfer stop",
          delta="⚠ warning" if det["summary"]["missed_connections"] > 0 else None,
          delta_color="inverse")
c4.metric("Constraint Violations", val_report.n_violations,
          delta="FAIL" if not val_report.passed else "PASS",
          delta_color="inverse" if not val_report.passed else "normal")

st.divider()

# ── Independent validator ──────────────────────────────────────────────────────
st.subheader("🛡️ Independent Constraint Validator")
st.caption("Runs separately from the optimizer — results cannot be influenced by the recommendation engine.")

for check in val_report.checks:
    color = "#276749" if check.passed else "#742a2a"
    bg    = "rgba(39,103,73,0.12)" if check.passed else "rgba(116,42,42,0.18)"
    icon  = "✅" if check.passed else "❌"
    st.markdown(
        f'<div style="background:{bg};border-left:3px solid {color};padding:8px 14px;'
        f'border-radius:6px;margin:4px 0">'
        f'{icon} <b>{check.constraint}</b><br>'
        f'<small style="color:#a0aec0">{check.detail}</small></div>',
        unsafe_allow_html=True,
    )

st.divider()

tab1, tab2, tab3 = st.tabs(["🔴 Overcrowding", "🔗 Missed Connections", "📊 Load Profile"])

with tab1:
    overcrowding = det["overcrowding"]
    if not overcrowding:
        st.success("No overcrowding events detected for this seed. "
                   "Try the Disruptions page to introduce stress scenarios.")
    else:
        rows = [{
            "Departure": v.trip.departure.departure_id,
            "Route": v.trip.departure.route.name,
            "Dep Time": fmt_time(v.trip.departure.departure_time),
            "Stop": v.stop_event.stop.name,
            "On Board": v.stop_event.on_board_after,
            "Capacity": v.stop_event.capacity,
            "Over By": v.stop_event.on_board_after - v.stop_event.capacity,
            "Unmet": v.stop_event.unmet_demand,
            "Severity": v.severity.upper(),
        } for v in overcrowding]
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, use_container_width=True)
        by_route = df.groupby("Route")["Over By"].sum().reset_index()
        fig = go.Figure(go.Bar(x=by_route["Route"], y=by_route["Over By"],
            marker_color="#fc8181", text=by_route["Over By"], textposition="outside"))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)", height=240, margin=dict(l=0,r=0,t=20,b=0),
            title="Total Passengers Over Capacity by Route",
            xaxis_title="Route", yaxis_title="Passengers over capacity")
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    missed = det["missed_connections"]
    if not missed:
        st.success(f"No missed connections detected. "
                   f"(Threshold: extra wait > {MAX_WAIT_FOR_CONNECTION:.0f} min)")
    else:
        rows = [{
            "Transfer Stop": mc.transfer_stop.name,
            "Arriving Route": mc.arriving_route.name,
            "Onward Route": mc.onward_route.name,
            "Arrival at Stop": fmt_time(mc.actual_arrival_at_transfer),
            "Bus Left at": fmt_time(mc.onward_bus_departure),
            "Extra Wait (min)": mc.extra_wait_minutes,
            "Next Bus": fmt_time(mc.next_onward_departure) if mc.next_onward_departure else "None",
        } for mc in missed]
        df_mc = pd.DataFrame(rows)
        st.dataframe(df_mc, hide_index=True, use_container_width=True)
        by_stop = df_mc.groupby("Transfer Stop")["Extra Wait (min)"].sum().reset_index()
        fig2 = go.Figure(go.Bar(x=by_stop["Transfer Stop"], y=by_stop["Extra Wait (min)"],
            marker_color="#f6ad55", text=by_stop["Extra Wait (min)"].apply(lambda v: f"{v:.0f}"),
            textposition="outside"))
        fig2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)", height=240, margin=dict(l=0,r=0,t=20,b=0),
            title="Total Extra Wait by Transfer Stop",
            xaxis_title="Stop", yaxis_title="Total extra wait (min)")
        st.plotly_chart(fig2, use_container_width=True)

with tab3:
    st.subheader("Passenger Load Heatmap")
    import numpy as np
    sampled = trips[:120]
    heatmap_rows = []
    for trip in sampled:
        dt = trip.departure.departure_time
        for ev in trip.stop_events:
            heatmap_rows.append({
                "Time": fmt_time(dt),
                "Stop": ev.stop.name,
                "Load": ev.on_board_after / ev.capacity,
            })
    if heatmap_rows:
        df_h = pd.DataFrame(heatmap_rows)
        pivot = df_h.pivot_table(index="Stop", columns="Time", values="Load", aggfunc="mean")
        fig3 = go.Figure(go.Heatmap(
            z=pivot.values, x=list(pivot.columns), y=list(pivot.index),
            colorscale=[[0, "rgba(26,54,93,0.3)"], [0.85, "#63b3ed"], [1.0, "#fc8181"]],
            zmin=0, zmax=1.2, colorbar=dict(title="Load fraction")))
        fig3.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)", height=360, margin=dict(l=0,r=0,t=20,b=0),
            xaxis=dict(title="Departure Time", tickangle=-45), yaxis_title="Stop")
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Red > 100% capacity. Blue = comfortable. Near-white = near-empty.")
