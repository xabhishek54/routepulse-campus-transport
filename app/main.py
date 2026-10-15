"""
RoutePulse — Landing dashboard

Shows today's live snapshot: how stressed is the network right now?
Answers: "Is everything running OK?" and "Where do I need to act?"
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(
    page_title="RoutePulse — Campus Transport",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from app.utils import inject_css, load_campus, get_simulation, page_header, stat_card
from app.utils import ACCENT, SUCCESS, WARNING, DANGER, NEUTRAL

inject_css()

# ─── Header ───────────────────────────────────────────────────────────────────
st.markdown(
    f"""
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:8px">
        <div style="font-size:2.4rem;line-height:1">⬡</div>
        <div>
            <h1 style="margin:0;font-size:2rem">RoutePulse</h1>
            <p style="margin:0;color:{NEUTRAL};font-size:14px">
                Westbrook University — Campus Transport Intelligence
            </p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
st.divider()

# ─── Global controls ──────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### Controls")
    st.markdown(f"<p style='color:{NEUTRAL};font-size:12px'>These settings apply to all pages.</p>", unsafe_allow_html=True)
    st.divider()

    selected_seed = st.slider(
        "Simulation run",
        min_value=42, max_value=52, value=42, step=1,
        help="Each run uses a different random demand pattern. Run 42 is the default; try several to see the spread."
    )
    st.session_state["selected_seed"] = selected_seed

    st.divider()
    st.markdown(f"<p style='color:{NEUTRAL};font-size:11px'>Westbrook University is a fictional synthetic campus. No real passenger data is used.</p>", unsafe_allow_html=True)
    st.markdown(f"<p style='color:{NEUTRAL};font-size:11px'>Reproduce all results:</p>", unsafe_allow_html=True)
    st.code("python eval/run_evaluation.py", language="bash")

# ─── Load data ────────────────────────────────────────────────────────────────
stops, routes, vehicles, departures, naive, smarter = load_campus()
seed = st.session_state.get("selected_seed", 42)

# Run naive baseline for the snapshot
plan, trips = get_simulation("baseline_naive", seed)

if not trips:
    st.error("Simulation returned no trips. Check data generation.")
    st.stop()

# ─── Compute snapshot metrics ─────────────────────────────────────────────────
total_demand  = sum(ev.demand_at_stop for t in trips for ev in t.stop_events)
total_boarded = sum(ev.boarded for t in trips for ev in t.stop_events)
service_rate  = total_boarded / total_demand if total_demand > 0 else 0
crowding_events = sum(1 for t in trips for ev in t.stop_events if ev.crowded)
total_unmet   = sum(t.total_unmet_demand for t in trips)
all_delays    = [ev.delay for t in trips for ev in t.stop_events]
avg_delay     = sum(max(0, d) for d in all_delays) / len(all_delays) if all_delays else 0

# Colour code the service rate
sr_color = SUCCESS if service_rate >= 0.8 else (WARNING if service_rate >= 0.6 else DANGER)

# ─── Status snapshot ──────────────────────────────────────────────────────────
st.markdown(f"### Today's network snapshot — Run {seed}")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:14px;margin-top:-12px'>Naive schedule (all minibuses, no adaptation) · Tap any card below for detail</p>",
    unsafe_allow_html=True
)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(
    "Service rate",
    f"{service_rate:.0%}",
    help="Fraction of arriving passengers who boarded. Higher is better."
)
c2.metric(
    "Passengers left behind",
    f"{total_unmet:,}",
    help="Total passengers who arrived at a stop and could not board due to a full vehicle."
)
c3.metric(
    "Stops where bus was full",
    f"{crowding_events}",
    help="Count of stop-events where at least one passenger could not board."
)
c4.metric(
    "Average delay",
    f"{avg_delay:.1f} min",
    help="Mean positive delay across all stops (how late buses run)."
)
c5.metric(
    "Routes in service",
    len(routes),
    help="Number of routes running today."
)

st.divider()

# ─── Route-by-route breakdown ─────────────────────────────────────────────────
st.markdown("### Route performance")

route_cols = st.columns(len(routes))
for col, (rid, route) in zip(route_cols, routes.items()):
    route_trips = [t for t in trips if t.departure.route.route_id == rid]
    if not route_trips:
        continue
    r_demand  = sum(ev.demand_at_stop for t in route_trips for ev in t.stop_events)
    r_boarded = sum(ev.boarded for t in route_trips for ev in t.stop_events)
    r_unmet   = sum(t.total_unmet_demand for t in route_trips)
    r_sr      = r_boarded / r_demand if r_demand > 0 else 0
    r_color   = SUCCESS if r_sr >= 0.8 else (WARNING if r_sr >= 0.6 else DANGER)

    with col:
        st.markdown(
            f'<div class="rp-card" style="text-align:center">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:{NEUTRAL};margin-bottom:8px">{rid}</div>'
            f'<div style="font-size:1.1rem;font-weight:600;color:{ACCENT};margin-bottom:4px">{route.name}</div>'
            f'<div style="font-size:2rem;font-weight:700;color:{r_color};margin-bottom:4px">{r_sr:.0%}</div>'
            f'<div style="font-size:12px;color:{NEUTRAL}">service rate</div>'
            f'<div style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(148,163,184,0.1)">'
            f'<span style="font-size:12px;color:{NEUTRAL}">{r_unmet:,} left behind</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.divider()

# ─── Quick guide ──────────────────────────────────────────────────────────────
st.markdown("### Where to look next")

guide = [
    ("Where is demand highest right now?",   "Demand map",        "01_Where_Is_the_Network_Under_Stress.py"),
    ("When will the next bus arrive?",        "Live arrivals",     "02_When_Will_My_Bus_Arrive.py"),
    ("What's going wrong in the schedule?",  "Violations",        "03_Whats_Going_Wrong.py"),
    ("What demand do we expect next hour?",  "Demand forecast",   "04_Demand_Forecast.py"),
    ("How should we change the schedule?",   "Recommendations",   "05_How_Should_We_Fix_It.py"),
    ("What happens if a bus breaks down?",   "Disruption planner","06_Disruption_Planner.py"),
]

g1, g2 = st.columns(2)
for i, (question, label, _) in enumerate(guide):
    target = g1 if i % 2 == 0 else g2
    with target:
        st.markdown(
            f'<div class="rp-card" style="display:flex;align-items:center;gap:14px;cursor:pointer">'
            f'<div style="width:36px;height:36px;border-radius:50%;background:rgba(96,165,250,0.15);'
            f'border:1px solid rgba(96,165,250,0.3);display:flex;align-items:center;justify-content:center;'
            f'font-size:14px;font-weight:700;color:{ACCENT};flex-shrink:0">{i+1}</div>'
            f'<div>'
            f'<div style="font-size:13px;font-weight:500;color:#e2e8f0">{question}</div>'
            f'<div style="font-size:11px;color:{NEUTRAL};margin-top:2px">→ {label}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

st.divider()

# ─── Architecture note ────────────────────────────────────────────────────────
with st.expander("How RoutePulse works", expanded=False):
    st.markdown(f"""
**Simulation** — Stochastic discrete-event simulator. Each stop samples Poisson demand scaled
by time-of-day multipliers (sharp peaks at 08:30, 09:00, 12:00, 17:00). Travel times have
Gaussian noise (σ = 1.5 min/segment).

**ETA estimation** — 1D Kalman filter tracks delay state stop-by-stop along a route.
Process noise σ = {1.2} min/stop, observation noise σ = {1.0} min. Stated CI: 90%.
Calibration measured independently over all trips and seeds; target calibration ≈ 90%.

**Optimizer** — Greedy: (1) upgrade vehicles on overcrowded trips, (2) insert extra departures
where gaps remain, (3) shift departure times to fix missed connections. Every recommended plan
is validated by an independent constraint checker (7 checks) before display.

**Baselines** — Two comparison baselines are computed:
- *Naive*: all routes use 30-seat minibuses all day, no adaptation.
- *Rule-based*: upgrades entire routes to 60-seat buses when peak demand exceeds 80% of
  minibus capacity. Blunt: pays for large buses all day, can't add trips or shift times.

**Evaluation** — 11 deterministic seeds (42–52). Every number shown is computed from simulation
data; no fabricated estimates.

Metrics are defined in `routepulse/config.py`. Service rate = boarded / total demand.
Crowding event = any stop where unmet_demand > 0 (passenger couldn't board).
""")
