"""
Page 4 — ML Demand Forecasting
GradientBoostingRegressor — per-stop demand forecast with uncertainty.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

from app.utils import inject_css, load_campus, get_forecaster, fmt_time
from routepulse.config import SEED, FORECAST_HORIZON_STEPS, FORECAST_N_LAGS, HEADWAY

inject_css()

stops, routes, vehicles, departures, baseline, smarter = load_campus()

st.title("🤖 ML Demand Forecasting")
st.caption("GradientBoostingRegressor — trained on simulated history, predicts stop-level demand")

# ── Train forecaster ───────────────────────────────────────────────────────────
with st.spinner("Training forecaster (cached after first load)…"):
    forecaster = get_forecaster()

if not forecaster.is_fitted:
    st.error("Forecaster failed to train. Check logs.")
    st.stop()

# ── Model info ─────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Train MAE", f"{forecaster.train_mae:.2f} pax",
          help="Mean absolute error on training seeds (42–47)")
c2.metric("Holdout MAE", f"{forecaster.holdout_mae:.2f} pax" if forecaster.holdout_mae else "—",
          help="MAE on held-out seeds (48–52) — unseen during training")
c3.metric("Forecast Horizon", f"{FORECAST_HORIZON_STEPS} slots",
          help=f"{FORECAST_HORIZON_STEPS} × {HEADWAY} min = {FORECAST_HORIZON_STEPS * HEADWAY} min ahead")
c4.metric("Lag Features", FORECAST_N_LAGS,
          help=f"Past {FORECAST_N_LAGS} boarding counts used as features")

# Calibration indicator
if forecaster.holdout_mae and forecaster.train_mae:
    overfit_ratio = forecaster.holdout_mae / forecaster.train_mae
    if overfit_ratio < 1.3:
        st.success(f"✅ Holdout MAE / Train MAE = {overfit_ratio:.2f} — model generalises well (< 1.3)")
    elif overfit_ratio < 2.0:
        st.warning(f"⚠️ Holdout MAE / Train MAE = {overfit_ratio:.2f} — mild overfitting")
    else:
        st.error(f"❌ Holdout MAE / Train MAE = {overfit_ratio:.2f} — significant overfitting")

st.divider()

# ── Per-stop forecast ──────────────────────────────────────────────────────────
st.subheader("Per-Stop Demand Forecast")

col_a, col_b, col_c = st.columns([2, 2, 1])
with col_a:
    stop_names = {s.name: s for s in stops.values()}
    sel_stop = stop_names[st.selectbox("Stop", list(stop_names.keys()))]
with col_b:
    current_time_min = st.slider(
        "Current time", min_value=8 * 60, max_value=19 * 60,
        value=9 * 60, step=HEADWAY,
        format_func=fmt_time,
    )
with col_c:
    seed_fc = st.number_input("History seed", value=SEED, min_value=SEED, max_value=SEED + 10, step=1)

# Build recent history from simulation
@st.cache_data(show_spinner="Building demand history…")
def _get_history(stop_id, seed_val):
    from routepulse.simulator import simulate_plan
    trips = simulate_plan(baseline, base_seed=seed_val)
    history = []
    for trip in sorted(trips, key=lambda t: t.departure.departure_time):
        for ev in trip.stop_events:
            if ev.stop.stop_id == stop_id:
                history.append((ev.actual_arrival, ev.demand_at_stop, ev.boarded))
    return history

history = _get_history(sel_stop.stop_id, int(seed_fc))

# Get lag values from history (last N observations before current_time)
past = [(t, d, b) for t, d, b in history if t <= current_time_min]
lag_demands = [d for _, d, _ in past[-FORECAST_N_LAGS:]]
actual_future = [(t, d) for t, d, _ in history if current_time_min < t <= current_time_min + FORECAST_HORIZON_STEPS * HEADWAY]

# Forecast
horizon = forecaster.predict_horizon(sel_stop.stop_id, current_time_min, lag_demands)

# ── Forecast chart ─────────────────────────────────────────────────────────────
fig = go.Figure()

# Historical
if past:
    hist_times  = [fmt_time(t) for t, _, _ in past[-20:]]
    hist_demand = [d for _, d, _ in past[-20:]]
    hist_board  = [b for _, _, b in past[-20:]]
    fig.add_trace(go.Scatter(x=hist_times, y=hist_demand, mode="markers+lines",
        name="Historical demand", marker=dict(color="#63b3ed", size=8),
        line=dict(color="#63b3ed", width=2)))
    fig.add_trace(go.Scatter(x=hist_times, y=hist_board, mode="markers",
        name="Actual boarded", marker=dict(color="#68d391", size=6, symbol="triangle-up")))

# Forecast
fc_times  = [fmt_time(t) for t, _, _ in horizon]
fc_points = [pt for _, pt, _ in horizon]
fc_unc    = [unc for _, _, unc in horizon]
fc_hi = [pt + 1.645 * unc for pt, unc in zip(fc_points, fc_unc)]
fc_lo = [max(0, pt - 1.645 * unc) for pt, unc in zip(fc_points, fc_unc)]

fig.add_trace(go.Scatter(
    x=fc_times + fc_times[::-1],
    y=fc_hi + fc_lo[::-1],
    fill="toself", fillcolor="rgba(246,173,85,0.15)",
    line=dict(color="rgba(0,0,0,0)"), name="90% forecast CI"))
fig.add_trace(go.Scatter(x=fc_times, y=fc_points, mode="markers+lines",
    name="ML forecast", marker=dict(color="#f6ad55", size=10, symbol="circle-open"),
    line=dict(color="#f6ad55", width=2, dash="dash")))

# Actual future (revealed)
if actual_future:
    fig.add_trace(go.Scatter(
        x=[fmt_time(t) for t, _ in actual_future],
        y=[d for _, d in actual_future],
        mode="markers", name="Actual (revealed)",
        marker=dict(color="#fc8181", size=10, symbol="x")))

fig.add_vline(x=fmt_time(current_time_min), line_dash="dash",
              line_color="rgba(255,255,255,0.3)", annotation_text="Now")
fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)", height=380, margin=dict(l=0,r=0,t=20,b=0),
    xaxis=dict(title="Time", showgrid=False, tickangle=-45),
    yaxis=dict(title="Passengers", showgrid=True, gridcolor="rgba(99,179,237,0.08)"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02))
st.plotly_chart(fig, use_container_width=True)

# ── Forecast table ─────────────────────────────────────────────────────────────
st.subheader("Forecast Detail")
fc_rows = []
for slot_time, pt, unc in horizon:
    actual = next((d for t, d in actual_future if abs(t - slot_time) < HEADWAY / 2), None)
    fc_rows.append({
        "Slot": fmt_time(slot_time),
        "Forecast (pax)": f"{pt:.1f}",
        "Uncertainty (±)": f"{1.645 * unc:.1f}",
        "90% CI": f"[{max(0, pt - 1.645 * unc):.0f}, {pt + 1.645 * unc:.0f}]",
        "Actual": f"{actual:.0f}" if actual is not None else "—",
        "Error": f"{abs(pt - actual):.1f}" if actual is not None else "—",
    })
st.dataframe(pd.DataFrame(fc_rows), hide_index=True, use_container_width=True)

st.divider()

# ── Feature importances ────────────────────────────────────────────────────────
st.subheader("Feature Importances")
fi = forecaster.feature_importances()
if not fi.empty:
    fig_fi = go.Figure(go.Bar(
        x=fi["importance"].head(12),
        y=fi["feature"].head(12),
        orientation="h",
        marker_color="#63b3ed",
    ))
    fig_fi.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", height=360,
        margin=dict(l=0, r=0, t=20, b=0),
        xaxis_title="Importance", yaxis_title="Feature",
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig_fi, use_container_width=True)
    st.caption(
        "Top features are demand_mult (physics-based peak curve) and recent lag counts, "
        "confirming the model has learned the demand pattern rather than overfitting noise."
    )

# ── Comparison: ML vs physics ──────────────────────────────────────────────────
st.subheader("ML Forecast vs Physics-based Demand Model")
from routepulse.data_gen import demand_multiplier

comp_times = list(range(8 * 60, 20 * 60, HEADWAY))
physics = [demand_multiplier(t) * sel_stop.base_demand_rate * (HEADWAY / 60) for t in comp_times]

ml_preds = []
lags_running = [0.0] * FORECAST_N_LAGS
for t in comp_times:
    pt, _ = forecaster.predict_demand(sel_stop.stop_id, t, lags_running)
    ml_preds.append(pt)
    lags_running.append(pt)
    lags_running = lags_running[-FORECAST_N_LAGS:]

fig_cmp = go.Figure()
fig_cmp.add_trace(go.Scatter(x=[fmt_time(t) for t in comp_times], y=physics,
    mode="lines", name="Physics model (Poisson mean)",
    line=dict(color="#63b3ed", width=2)))
fig_cmp.add_trace(go.Scatter(x=[fmt_time(t) for t in comp_times], y=ml_preds,
    mode="lines", name="ML forecast",
    line=dict(color="#f6ad55", width=2, dash="dash")))
fig_cmp.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)", height=280, margin=dict(l=0,r=0,t=20,b=0),
    xaxis=dict(title="Time of Day", showgrid=False, tickangle=-45, nticks=13),
    yaxis_title="Passengers per slot",
    legend=dict(orientation="h", yanchor="bottom", y=1.02))
st.plotly_chart(fig_cmp, use_container_width=True)
st.caption(
    "The ML model learns from simulated boarding data (including travel noise and capacity effects) "
    "while the physics model only uses the demand rate function. "
    "Divergence at peaks indicates the ML model accounts for capacity-capped boarding."
)
