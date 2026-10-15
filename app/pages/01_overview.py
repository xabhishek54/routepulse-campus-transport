"""
Page 1 — Route & Stop Overview
Interactive campus map with route selector and live schedule table.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Overview — RoutePulse", page_icon="🗺️", layout="wide")

# shared CSS
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
    from routepulse.data_gen import build_campus
    return build_campus()


stops, routes, vehicles, departures = load_campus()

st.title("🗺️ Route & Stop Overview")
st.caption("Westbrook University — Synthetic Campus")

# ── Route selector ────────────────────────────────────────────────────────────
route_options = {"All Routes": None} | {r.name: r for r in routes.values()}
selected_label = st.selectbox("Filter by route", list(route_options.keys()))
selected_route = route_options[selected_label]

# ── Campus map ────────────────────────────────────────────────────────────────
ROUTE_COLORS = {"R1": "#63b3ed", "R2": "#68d391", "R3": "#f6ad55"}

center_lat = sum(s.lat for s in stops.values()) / len(stops)
center_lon = sum(s.lon for s in stops.values()) / len(stops)

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=15,
    tiles="CartoDB dark_matter",
)

# Draw route lines
routes_to_draw = [selected_route] if selected_route else list(routes.values())
for route in routes_to_draw:
    color = ROUTE_COLORS.get(route.route_id, "#ffffff")
    coords = [(rs.stop.lat, rs.stop.lon) for rs in route.route_stops]
    folium.PolyLine(
        coords,
        color=color,
        weight=4,
        opacity=0.85,
        tooltip=route.name,
    ).add_to(m)

# Draw stop markers
for stop in stops.values():
    # Is this stop on the selected route?
    on_selected = (
        selected_route is None
        or stop.stop_id in {rs.stop.stop_id for rs in selected_route.route_stops}
    )
    if not on_selected:
        continue
    routes_serving = [r.name for r in routes.values() if stop.stop_id in {rs.stop.stop_id for rs in r.route_stops}]
    popup_html = f"""
    <div style="font-family:Inter,sans-serif;min-width:160px">
        <b style="font-size:14px">{stop.name}</b><br>
        <small style="color:#666">ID: {stop.stop_id}</small><br>
        <b>Routes:</b> {', '.join(routes_serving)}<br>
        <b>Peak demand:</b> {stop.base_demand_rate:.0f} pax/hr
    </div>
    """
    folium.CircleMarker(
        location=[stop.lat, stop.lon],
        radius=9,
        color="#ffffff",
        weight=2,
        fill=True,
        fill_color="#2b6cb0",
        fill_opacity=0.9,
        popup=folium.Popup(popup_html, max_width=220),
        tooltip=stop.name,
    ).add_to(m)

col_map, col_info = st.columns([3, 1])
with col_map:
    st_folium(m, width=None, height=420, returned_objects=[])

with col_info:
    st.subheader("Stops")
    for stop in stops.values():
        on_route = selected_route is None or stop.stop_id in {rs.stop.stop_id for rs in selected_route.route_stops}
        if on_route:
            st.markdown(f"**{stop.name}**  \n`{stop.stop_id}` · {stop.base_demand_rate:.0f} pax/hr peak")

# ── Route details ─────────────────────────────────────────────────────────────
st.subheader("Route Details")
tab_cols = st.columns(len(routes))
for col, (rid, route) in zip(tab_cols, routes.items()):
    color = ROUTE_COLORS.get(rid, "#ffffff")
    with col:
        st.markdown(f'<span style="color:{color};font-weight:700;font-size:16px">■ {route.name}</span>', unsafe_allow_html=True)
        rows = []
        for rs in route.route_stops:
            rows.append({
                "Stop": rs.stop.name,
                "Cumulative (min)": rs.cumulative_time,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

# ── Schedule table ────────────────────────────────────────────────────────────
st.subheader("Today's Schedule")

def fmt_time(m):
    h, mn = divmod(int(m), 60)
    return f"{h:02d}:{mn:02d}"

sched_rows = []
for dep in departures:
    if selected_route and dep.route.route_id != selected_route.route_id:
        continue
    sched_rows.append({
        "Route": dep.route.name,
        "Departure": fmt_time(dep.departure_time),
        "Vehicle": dep.vehicle.vehicle_id,
        "Capacity": dep.vehicle.capacity,
        "Type": dep.vehicle.vehicle_type.name,
        "Final Stop": dep.route.route_stops[-1].stop.name,
        "Journey (min)": dep.route.total_nominal_time,
    })

df = pd.DataFrame(sched_rows)
st.dataframe(df, hide_index=True, use_container_width=True, height=320)

# ── Demand curve ──────────────────────────────────────────────────────────────
st.subheader("Demand Profile (Time of Day)")
from routepulse.data_gen import demand_multiplier
import numpy as np

times = np.linspace(8 * 60, 20 * 60, 300)
mults = [demand_multiplier(t) for t in times]
time_labels = [fmt_time(t) for t in times]

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=time_labels,
    y=mults,
    mode="lines",
    fill="tozeroy",
    fillcolor="rgba(99,179,237,0.15)",
    line=dict(color="#63b3ed", width=2.5),
    name="Demand multiplier",
))
fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    height=250,
    margin=dict(l=0, r=0, t=20, b=0),
    xaxis=dict(title="Time of Day", showgrid=False, tickangle=-45, nticks=12),
    yaxis=dict(title="Demand Multiplier", showgrid=True, gridcolor="rgba(99,179,237,0.1)"),
    showlegend=False,
)
st.plotly_chart(fig, use_container_width=True)
