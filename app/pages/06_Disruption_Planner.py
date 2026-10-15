"""
Page: What happens if something goes wrong?

Disruption scenario planner: pick a disruption, see the impact on metrics,
then see what RoutePulse recommends to recover.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from app.utils import inject_css, load_campus, get_simulation, page_header, fmt_time
from app.utils import ACCENT, SUCCESS, WARNING, DANGER, NEUTRAL

st.set_page_config(page_title="Disruptions — RoutePulse", page_icon="⬡", layout="wide")
inject_css()
page_header(
    "What happens if something goes wrong?",
    "Named disruption scenarios · Impact metrics · RoutePulse recovery plan"
)

# ─── Load ─────────────────────────────────────────────────────────────────────
stops, routes, vehicles, departures, naive, smarter = load_campus()
seed = st.session_state.get("selected_seed", 42)

from routepulse.scenarios import get_all_scenarios

all_scenarios = get_all_scenarios(naive)
scenario_map = {s.scenario_id: s for s in all_scenarios}

SCENARIO_ICONS = {
    "sports_event":       "🏟",
    "morning_traffic":    "🚧",
    "vehicle_breakdown":  "🔧",
    "compound":           "⚠",
}

with st.sidebar:
    st.markdown("### Select scenario")
    scenario_choice = st.selectbox(
        "Disruption scenario",
        options=[s.scenario_id for s in all_scenarios],
        format_func=lambda sid: f"{SCENARIO_ICONS.get(sid, '')} {scenario_map[sid].name}",
    )

selected = scenario_map[scenario_choice]

# ─── Scenario info card ────────────────────────────────────────────────────────
st.markdown(
    f'<div class="rp-card" style="border-color:rgba(251,191,36,0.3)">'
    f'<div style="font-size:1.3rem;font-weight:700;color:{WARNING};margin-bottom:8px">'
    f'{SCENARIO_ICONS.get(selected.scenario_id, "")} {selected.name}</div>'
    f'<div style="font-size:14px;color:{NEUTRAL};line-height:1.7">{selected.description}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ─── Run baseline and disrupted simulations ─────────────────────────────────────
plan_base, trips_base = get_simulation("baseline_naive", seed)
plan_dis, trips_dis = get_simulation("baseline_naive", seed, disruption_ids=(selected.scenario_id,))

# ─── Impact metrics ───────────────────────────────────────────────────────────
def _metrics(trips):
    total_demand  = sum(ev.demand_at_stop for t in trips for ev in t.stop_events)
    total_boarded = sum(ev.boarded for t in trips for ev in t.stop_events)
    unmet         = sum(t.total_unmet_demand for t in trips)
    crowded       = sum(1 for t in trips for ev in t.stop_events if ev.crowded)
    delays        = [ev.delay for t in trips for ev in t.stop_events]
    avg_delay     = sum(max(0, d) for d in delays) / len(delays) if delays else 0
    sr            = total_boarded / total_demand if total_demand > 0 else 0
    cancelled     = sum(1 for t in trips if not t.stop_events)
    return {
        "service_rate": sr, "unmet": unmet, "crowded": crowded,
        "avg_delay": avg_delay, "cancelled": cancelled,
    }

m_base = _metrics(trips_base)
m_dis  = _metrics(trips_dis)

st.markdown("### Impact: normal vs disrupted")
c1, c2, c3, c4 = st.columns(4)

def _delta_metric(col, label, base_val, dis_val, fmt=".0%", lower_is_better=True, unit=""):
    delta = dis_val - base_val
    delta_str = f"{delta:+.1f}{unit}" if unit else f"{delta:+.1%}" if "%" in fmt else f"{delta:+.1f}"
    color = DANGER if (lower_is_better and delta > 0) or (not lower_is_better and delta < 0) else SUCCESS
    col.metric(
        label,
        f"{dis_val:{fmt}}{unit}",
        delta=delta_str,
        delta_color="inverse" if lower_is_better else "normal",
        help=f"Normal: {base_val:{fmt}}{unit}"
    )

_delta_metric(c1, "Service rate",         m_base["service_rate"], m_dis["service_rate"], ".0%", lower_is_better=False)
_delta_metric(c2, "Passengers left behind", m_base["unmet"],      m_dis["unmet"],        ".0f", lower_is_better=True, unit="")
_delta_metric(c3, "Crowded stops",         m_base["crowded"],     m_dis["crowded"],       ".0f", lower_is_better=True)
_delta_metric(c4, "Avg delay",             m_base["avg_delay"],   m_dis["avg_delay"],     ".1f", lower_is_better=True, unit=" min")

if m_dis["cancelled"] > 0:
    st.warning(
        f"{m_dis['cancelled']} trip(s) cancelled due to vehicle breakdown. "
        "Passengers on these routes have no service during the gap.",
        icon="🔧"
    )

st.divider()

# ─── RoutePulse recovery plan ──────────────────────────────────────────────────
st.markdown("### RoutePulse recovery recommendation")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>"
    f"Optimizer re-runs against the disrupted simulation to find targeted fixes.</p>",
    unsafe_allow_html=True
)

from routepulse.detector import detect_all
from routepulse.optimizer import build_recommended_plan, action_summary
from routepulse.validator import validate

det_dis = detect_all(plan_dis, trips_dis)
plan_rec = build_recommended_plan(plan_dis, trips_dis, det_dis["missed_connections"])
val_rec  = validate(plan_rec)

from routepulse.simulator import simulate_plan, DelayDisruption, DemandSpikeDisruption, VehicleBreakdownDisruption
trips_rec = simulate_plan(plan_rec, base_seed=seed,
                          disruptions=selected.disruptions if hasattr(selected, "disruptions") else None)
m_rec = _metrics(trips_rec)

acts = action_summary(plan_rec.actions_applied)

ra, rb, rc, rd = st.columns(4)
ra.metric("Actions taken", acts["total_actions"])
rb.metric("Passengers helped", f"~{acts['passengers_accommodated']:,}")
rc.metric(
    "Recovery service rate",
    f"{m_rec['service_rate']:.0%}",
    delta=f"{m_rec['service_rate'] - m_dis['service_rate']:+.0%}",
    delta_color="normal",
)
rd.metric(
    "Constraint violations",
    val_rec.n_violations,
    delta="0" if val_rec.passed else f"+{val_rec.n_violations}",
    delta_color="normal" if val_rec.passed else "inverse",
)

# ─── Timeline: delay by departure ─────────────────────────────────────────────
st.markdown("### Delay timeline: normal vs disrupted vs recovered")

timeline_rows = []
for label, trips_set, color in [
    ("Normal", trips_base, SUCCESS),
    ("Disrupted", trips_dis, DANGER),
    ("Recovered", trips_rec, ACCENT),
]:
    for trip in trips_set:
        dep_h = trip.departure.departure_time
        avg_d = sum(max(0, ev.delay) for ev in trip.stop_events) / len(trip.stop_events) if trip.stop_events else 0
        timeline_rows.append({
            "scenario": label,
            "dep_time": dep_h,
            "avg_delay": avg_d,
            "route": trip.departure.route.name,
            "color": color,
        })

fig = go.Figure()
for label, color in [("Normal", SUCCESS), ("Disrupted", DANGER), ("Recovered", ACCENT)]:
    subset = [r for r in timeline_rows if r["scenario"] == label]
    if not subset:
        continue
    fig.add_trace(go.Scatter(
        x=[fmt_time(r["dep_time"]) for r in subset],
        y=[r["avg_delay"] for r in subset],
        mode="lines+markers",
        name=label,
        line=dict(color=color, width=1.5),
        marker=dict(size=5, color=color),
        hovertemplate=(
            f"<b>{label}</b> · %{{customdata}}<br>"
            "Dep: %{x}<br>Avg delay: %{y:.1f} min<extra></extra>"
        ),
        customdata=[r["route"] for r in subset],
    ))

fig.add_hline(y=0, line_dash="dot", line_color=NEUTRAL, line_width=1)
fig.update_layout(
    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(title="Departure time", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
    yaxis=dict(title="Average delay per trip (min)", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
    font=dict(color=NEUTRAL),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=NEUTRAL)),
    height=340, margin=dict(l=10, r=20, t=20, b=30),
)
st.plotly_chart(fig, use_container_width=True)
