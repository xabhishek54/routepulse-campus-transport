"""
Page: What's going wrong?

Shows constraint violations, crowded stops, and missed connections.
All constraints are independently checked — separate from the optimizer.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from app.utils import inject_css, load_campus, get_simulation, page_header, validation_badge, fmt_time
from app.utils import ACCENT, SUCCESS, WARNING, DANGER, NEUTRAL

st.set_page_config(page_title="Violations — RoutePulse", page_icon="⬡", layout="wide")
inject_css()
page_header(
    "What's going wrong?",
    "Independent constraint checker · Crowded stops · Missed connections"
)

# ─── Load ─────────────────────────────────────────────────────────────────────
stops, routes, vehicles, naive, naive_plan, smarter = load_campus()
seed = st.session_state.get("selected_seed", 42)

with st.sidebar:
    st.markdown("### Schedule to audit")
    plan_choice = st.selectbox(
        "Which schedule?",
        ["Naive (all minibuses)", "Rule-based (upgraded routes)", "RoutePulse recommendation"],
    )
    plan_id = (
        "baseline_naive" if "Naive" in plan_choice
        else "baseline_smarter" if "Rule-based" in plan_choice
        else "optimised"
    )

plan, trips = get_simulation(plan_id, seed)
from routepulse.detector import detect_all
from routepulse.validator import validate

det = detect_all(plan, trips)
val = validate(plan)

# ─── Top-line ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Constraint violations",
    val.n_violations,
    help="Hard schedule rules checked by the independent validator (not the optimizer). See below for details."
)
c2.metric(
    "Crowded stops",
    det["summary"]["crowding_events"],
    help="Stops where at least one passenger could not board because the bus was full."
)
c3.metric(
    "Passengers left behind",
    f"{sum(t.total_unmet_demand for t in trips):,}",
    help="Total passengers who arrived at a stop and couldn't board across the whole day."
)
c4.metric(
    "Missed connections",
    det["summary"]["missed_connections"],
    help=f"Transfer failures where delay caused > 10 extra minutes of wait at a connecting stop."
)

st.divider()

# ─── Validator detail ─────────────────────────────────────────────────────────
st.markdown("### Hard constraint checks")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>These 7 checks are run independently of the optimizer — they cannot be gamed.</p>",
    unsafe_allow_html=True,
)

for check in val.checks:
    col_badge, col_text = st.columns([1, 8])
    with col_badge:
        if check.passed:
            st.markdown(f'<div class="rp-badge-ok">PASS</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="rp-badge-bad">FAIL</div>', unsafe_allow_html=True)
    with col_text:
        st.markdown(
            f'<div style="font-size:13px;color:{"#e2e8f0" if check.passed else DANGER};padding:2px 0">'
            f'<b>{check.constraint}</b></div>'
            f'<div style="font-size:12px;color:{NEUTRAL}">{check.detail}</div>',
            unsafe_allow_html=True,
        )

st.divider()

# ─── Crowding heatmap ─────────────────────────────────────────────────────────
st.markdown("### When and where do passengers get left behind?")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>Each cell = number of passengers who couldn't board. "
    f"Darker = more left behind. Click on a cell to see detail.</p>",
    unsafe_allow_html=True
)

# Build stop × time-slot matrix
slot_size = 30  # minutes
all_stops = list(stops.values())
stop_names = [s.name for s in all_stops]
slots = list(range(480, 1200, slot_size))  # 08:00–19:30

# matrix[stop_name][slot] = unmet_demand
matrix = {s.name: {sl: 0 for sl in slots} for s in all_stops}
for t in trips:
    for ev in t.stop_events:
        if ev.unmet_demand > 0:
            slot = int(ev.actual_arrival // slot_size) * slot_size
            if slot in matrix.get(ev.stop.name, {}):
                matrix[ev.stop.name][slot] += ev.unmet_demand

z_data    = [[matrix[sn].get(sl, 0) for sl in slots] for sn in stop_names]
x_labels  = [fmt_time(s) for s in slots]

fig_heat = go.Figure(go.Heatmap(
    z=z_data,
    x=x_labels,
    y=stop_names,
    colorscale=[[0, "rgba(15,23,42,0.5)"], [0.3, "rgba(251,191,36,0.6)"], [1, DANGER]],
    hovertemplate="<b>%{y}</b><br>%{x}<br>%{z} passengers left behind<extra></extra>",
    colorbar=dict(title="Passengers<br>left behind", tickfont=dict(color=NEUTRAL), bgcolor="rgba(0,0,0,0)"),
))
fig_heat.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(title="Time of day", color=NEUTRAL),
    yaxis=dict(title="Stop", color=NEUTRAL),
    font=dict(color=NEUTRAL),
    height=380, margin=dict(l=10, r=20, t=20, b=30),
)
st.plotly_chart(fig_heat, use_container_width=True)

# ─── Missed connections ────────────────────────────────────────────────────────
st.markdown("### Missed connection events")
missed = det["missed_connections"]

if not missed:
    st.success("No missed connections detected for this run.")
else:
    st.markdown(
        f"<p style='color:{NEUTRAL};font-size:13px'>"
        f"{len(missed)} events where a delayed arrival caused extra wait at a transfer stop "
        f"(threshold: more than 10 extra minutes)</p>",
        unsafe_allow_html=True,
    )
    mc_rows = []
    for mc in sorted(missed, key=lambda m: m.extra_wait_minutes, reverse=True)[:20]:
        mc_rows.append({
            "Transfer stop": mc.transfer_stop.name,
            "Arriving on": mc.arriving_route.name,
            "Connecting to": mc.onward_route.name,
            "Arrived at": fmt_time(mc.actual_arrival_at_transfer),
            "Bus left at": fmt_time(mc.onward_bus_departure),
            "Extra wait": f"{mc.extra_wait_minutes:.0f} min",
        })
    st.dataframe(
        pd.DataFrame(mc_rows),
        use_container_width=True,
        hide_index=True,
    )
    if len(missed) > 20:
        st.caption(f"Showing 20 of {len(missed)} missed connections. Worst cases first.")
