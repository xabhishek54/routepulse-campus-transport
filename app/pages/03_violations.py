"""
Page 3 — Violation Detection
Overcrowding, schedule conflicts, missed connections — with constraint validator.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Violations — RoutePulse", page_icon="⚠️", layout="wide")

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
def load_campus():
    from routepulse.data_gen import build_campus, build_baseline_plan
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    return stops, routes, vehicles, departures, baseline


@st.cache_data
def get_analysis(seed):
    from routepulse.data_gen import build_campus, build_baseline_plan
    from routepulse.simulator import simulate_plan
    from routepulse.detector import detect_all
    from routepulse.validator import validate
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    trips = simulate_plan(baseline, base_seed=seed)
    det = detect_all(baseline, trips)
    val_report = validate(baseline, trips)
    return trips, det, val_report


stops, routes, vehicles, departures, baseline = load_campus()

st.title("⚠️ Violation Detection")
st.caption("Independent constraint checker + overcrowding / missed-connection alerts")

seed = st.sidebar.number_input("Simulation seed", value=42, min_value=42, max_value=52, step=1)
trips, det, val_report = get_analysis(int(seed))

# ── Headline metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Overcrowding Events", det["summary"]["overcrowding_events"],
          delta="critical" if det["summary"]["overcrowding_events"] > 0 else None,
          delta_color="inverse")
c2.metric("Schedule Conflicts", det["summary"]["schedule_conflicts"])
c3.metric("Missed Connections", det["summary"]["missed_connections"],
          delta="warning" if det["summary"]["missed_connections"] > 0 else None,
          delta_color="inverse")
c4.metric("Constraint Violations", val_report.n_violations,
          delta="FAIL" if not val_report.passed else "PASS",
          delta_color="inverse" if not val_report.passed else "normal")

st.divider()

# ── Independent constraint validator ──────────────────────────────────────────
st.subheader("🛡️ Independent Constraint Validator")
st.caption("This checker runs separately from the optimizer — it cannot be gamed.")

for check in val_report.checks:
    icon = "✅" if check.passed else "❌"
    color = "#276749" if check.passed else "#742a2a"
    bg = "rgba(39,103,73,0.15)" if check.passed else "rgba(116,42,42,0.2)"
    st.markdown(
        f'<div style="background:{bg};border-left:3px solid {color};padding:8px 14px;'
        f'border-radius:6px;margin:4px 0">'
        f'{icon} <b>{check.constraint}</b><br>'
        f'<small style="color:#a0aec0">{check.detail}</small></div>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["🔴 Overcrowding", "🔗 Missed Connections", "📊 Load Profile"])

with tab1:
    overcrowding = det["overcrowding"]
    if not overcrowding:
        st.success("No overcrowding events detected for this seed.")
    else:
        rows = []
        for v in overcrowding:
            ev = v.stop_event
            rows.append({
                "Departure": v.trip.departure.departure_id,
                "Route": v.trip.departure.route.name,
                "Departure Time": fmt_time(v.trip.departure.departure_time),
                "Stop": ev.stop.name,
                "On Board": ev.on_board_after,
                "Capacity": ev.capacity,
                "Over By": ev.on_board_after - ev.capacity,
                "Unmet Demand": ev.unmet_demand,
                "Severity": v.severity.upper(),
            })
        df = pd.DataFrame(rows)
        # Colour-code severity
        st.dataframe(df, hide_index=True, use_container_width=True)

        # Bar chart: overcrowding by route
        by_route = df.groupby("Route")["Over By"].sum().reset_index()
        fig = go.Figure(go.Bar(
            x=by_route["Route"],
            y=by_route["Over By"],
            marker_color="#fc8181",
            text=by_route["Over By"],
            textposition="outside",
        ))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=250,
            margin=dict(l=0, r=0, t=20, b=0),
            title="Total Overcrowding by Route",
            xaxis_title="Route",
            yaxis_title="Total pax over capacity",
        )
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    missed = det["missed_connections"]
    if not missed:
        st.success("No missed connections detected for this seed.")
    else:
        rows = []
        for mc in missed:
            rows.append({
                "Transfer Stop": mc.transfer_stop.name,
                "Arriving Route": mc.arriving_route.name,
                "Onward Route": mc.onward_route.name,
                "Arrival at Stop": fmt_time(mc.actual_arrival_at_transfer),
                "Bus Left": fmt_time(mc.onward_bus_departure),
                "Extra Wait (min)": mc.extra_wait_minutes,
                "Next Bus": fmt_time(mc.next_onward_departure) if mc.next_onward_departure else "None",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # Summary by transfer stop
        df_mc = pd.DataFrame(rows)
        by_stop = df_mc.groupby("Transfer Stop")["Extra Wait (min)"].sum().reset_index()
        fig2 = go.Figure(go.Bar(
            x=by_stop["Transfer Stop"],
            y=by_stop["Extra Wait (min)"],
            marker_color="#f6ad55",
            text=by_stop["Extra Wait (min)"].apply(lambda v: f"{v:.0f} min"),
            textposition="outside",
        ))
        fig2.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=250,
            margin=dict(l=0, r=0, t=20, b=0),
            title="Total Extra Wait by Transfer Stop",
            xaxis_title="Stop",
            yaxis_title="Total extra wait (min)",
        )
        st.plotly_chart(fig2, use_container_width=True)

with tab3:
    st.subheader("Load Profile Across All Trips")
    # Heatmap: stop x departure time → load fraction
    import numpy as np

    stop_order = [s.name for s in stops.values()]
    # Sample a manageable number of trips
    sampled = trips[:120]
    heatmap_rows = []
    for trip in sampled:
        dep_time = trip.departure.departure_time
        for ev in trip.stop_events:
            heatmap_rows.append({
                "Time": f"{dep_time//60:.0f}:{dep_time%60:02.0f}",
                "Stop": ev.stop.name,
                "Load": ev.on_board_after / ev.capacity,
            })

    if heatmap_rows:
        df_h = pd.DataFrame(heatmap_rows)
        pivot = df_h.pivot_table(index="Stop", columns="Time", values="Load", aggfunc="mean")
        fig3 = go.Figure(go.Heatmap(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale=[[0, "rgba(26,54,93,0.3)"], [0.85, "#63b3ed"], [1.0, "#fc8181"]],
            zmin=0, zmax=1.2,
            colorbar=dict(title="Load fraction"),
        ))
        fig3.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=360,
            margin=dict(l=0, r=0, t=20, b=0),
            xaxis=dict(title="Departure Time", tickangle=-45),
            yaxis=dict(title="Stop"),
        )
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Red = overcrowded (>100% capacity). Blue = comfortable. White = empty.")
