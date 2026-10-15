"""
Page: Where is the network under stress?

Shows demand map, per-stop congestion, and demand curves throughout the day.
Operator question: "Which stops and routes are overloaded right now?"
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np

from app.utils import inject_css, load_campus, get_simulation, page_header, fmt_time
from app.utils import ACCENT, SUCCESS, WARNING, DANGER, NEUTRAL

st.set_page_config(page_title="Network Stress — RoutePulse", page_icon="⬡", layout="wide")
inject_css()
page_header(
    "Where is the network under stress?",
    "Stop-by-stop demand, crowding heatmap, and demand curves through the day"
)

# ─── Controls ─────────────────────────────────────────────────────────────────
stops, routes, vehicles, departures, naive, smarter = load_campus()
seed = st.session_state.get("selected_seed", 42)

with st.sidebar:
    st.markdown("### View options")
    view_plan = st.selectbox(
        "Schedule to analyse",
        ["Naive (all minibuses)", "Rule-based (upgraded routes)"],
        index=0,
        help="Naive uses 30-seat minibuses everywhere. Rule-based upgrades some routes to 60-seat buses."
    )
    plan_id = "baseline_naive" if "Naive" in view_plan else "baseline_smarter"

plan, trips = get_simulation(plan_id, seed)

if not trips:
    st.error("No trips returned. Check data generation.")
    st.stop()

# ─── Per-stop demand table ─────────────────────────────────────────────────────
st.markdown("### Demand and crowding by stop")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>Run {seed} · {view_plan} · "
    f"A 'crowded stop' is any arrival where someone could not board</p>",
    unsafe_allow_html=True
)

rows = []
for stop in stops.values():
    evs = [ev for t in trips for ev in t.stop_events if ev.stop.stop_id == stop.stop_id]
    if not evs:
        continue
    total_demand  = sum(e.demand_at_stop for e in evs)
    total_boarded = sum(e.boarded for e in evs)
    total_unmet   = sum(e.unmet_demand for e in evs)
    crowded_count = sum(1 for e in evs if e.crowded)
    sr = total_boarded / total_demand if total_demand > 0 else 1.0
    rows.append({
        "Stop": stop.name,
        "Total arrivals": total_demand,
        "Boarded": total_boarded,
        "Left behind": total_unmet,
        "Crowded departures": crowded_count,
        "Service rate": sr,
        "_sr": sr,  # raw for sorting
    })

df = pd.DataFrame(rows).sort_values("_sr")

# Service rate bar chart — horizontal, colour-coded
fig = go.Figure()
for _, row in df.iterrows():
    sr = row["Service rate"]
    color = SUCCESS if sr >= 0.80 else (WARNING if sr >= 0.60 else DANGER)
    fig.add_trace(go.Bar(
        x=[sr],
        y=[row["Stop"]],
        orientation="h",
        marker_color=color,
        name=row["Stop"],
        showlegend=False,
        hovertemplate=(
            f"<b>{row['Stop']}</b><br>"
            f"Service rate: {sr:.0%}<br>"
            f"Left behind: {row['Left behind']:,}<br>"
            f"Crowded departures: {row['Crowded departures']}"
            "<extra></extra>"
        ),
    ))

fig.add_vline(x=0.80, line_dash="dash", line_color=NEUTRAL, annotation_text="80% target",
              annotation_font_color=NEUTRAL, annotation_font_size=11)
fig.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(title="Service rate (fraction of passengers who boarded)",
               range=[0, 1], tickformat=".0%", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
    yaxis=dict(color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
    font=dict(color=NEUTRAL),
    height=380, margin=dict(l=10, r=20, t=20, b=30),
)
st.plotly_chart(fig, use_container_width=True)

# ─── Demand curve ─────────────────────────────────────────────────────────────
st.markdown("### Demand through the day")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>Total passengers arriving per 15-minute slot across all stops</p>",
    unsafe_allow_html=True
)

time_demand = {}
for t in trips:
    for ev in t.stop_events:
        slot = int(ev.actual_arrival // 15) * 15
        time_demand[slot] = time_demand.get(slot, 0) + ev.demand_at_stop

if time_demand:
    slots = sorted(time_demand)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=[fmt_time(s) for s in slots],
        y=[time_demand[s] for s in slots],
        fill="tozeroy",
        line=dict(color=ACCENT, width=2),
        fillcolor=f"rgba(96,165,250,0.15)",
        name="Total demand",
        hovertemplate="<b>%{x}</b><br>%{y} passengers<extra></extra>",
    ))
    fig2.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="Time of day", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
        yaxis=dict(title="Passengers arriving (15-min slot)", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
        font=dict(color=NEUTRAL),
        height=280, margin=dict(l=10, r=20, t=20, b=30),
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)

# ─── Map ──────────────────────────────────────────────────────────────────────
st.markdown("### Campus stop locations")
stop_rows = []
for stop in stops.values():
    evs = [ev for t in trips for ev in t.stop_events if ev.stop.stop_id == stop.stop_id]
    unmet = sum(e.unmet_demand for e in evs)
    demand = sum(e.demand_at_stop for e in evs)
    sr = (demand - unmet) / demand if demand > 0 else 1.0
    stop_rows.append({
        "name": stop.name,
        "lat": stop.lat, "lon": stop.lon,
        "unmet": unmet, "demand": demand,
        "service_rate": sr,
        "size": max(8, min(30, unmet / 50)),
    })
stop_df = pd.DataFrame(stop_rows)

fig3 = go.Figure()
fig3.add_trace(go.Scattermapbox(
    lat=stop_df["lat"], lon=stop_df["lon"],
    mode="markers+text",
    marker=dict(
        size=stop_df["size"] * 2,
        color=stop_df["service_rate"],
        colorscale=[[0, DANGER], [0.5, WARNING], [1, SUCCESS]],
        cmin=0.3, cmax=1.0,
        colorbar=dict(title="Service rate", tickformat=".0%", bgcolor="rgba(0,0,0,0)", tickfont=dict(color=NEUTRAL)),
    ),
    text=stop_df["name"],
    textposition="top right",
    textfont=dict(size=11, color="#e2e8f0"),
    hovertemplate=(
        "<b>%{text}</b><br>"
        "Service rate: %{marker.color:.0%}<br>"
        "Left behind: %{customdata[0]:,}<extra></extra>"
    ),
    customdata=stop_df[["unmet"]].values,
))
fig3.update_layout(
    mapbox=dict(
        style="carto-darkmatter",
        center=dict(lat=stop_df["lat"].mean(), lon=stop_df["lon"].mean()),
        zoom=14,
    ),
    margin=dict(l=0, r=0, t=0, b=0),
    height=380,
    paper_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig3, use_container_width=True)
st.caption("Stop size shows relative crowding. Red = many passengers left behind. Green = good service. Map uses OpenStreetMap (offline capable).")
