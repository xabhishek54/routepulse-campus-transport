"""
Page: What demand do we expect next hour?

ML demand forecast using Gradient Boosting. Shows stop-level forecasts,
compares to naive baseline, and displays train vs holdout error honestly.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from app.utils import inject_css, load_campus, get_forecaster, page_header, fmt_time
from app.utils import ACCENT, SUCCESS, WARNING, DANGER, NEUTRAL

st.set_page_config(page_title="Demand Forecast — RoutePulse", page_icon="⬡", layout="wide")
inject_css()
page_header(
    "What demand do we expect next hour?",
    "ML demand forecasting · Gradient Boosting trained on simulated data"
)

stops, routes, vehicles, departures, naive, smarter = load_campus()

# ─── Load forecaster ──────────────────────────────────────────────────────────
try:
    forecaster = get_forecaster()
except Exception as e:
    st.error(f"Could not load forecaster: {e}")
    st.markdown("The demand forecaster requires `scikit-learn`. Run `pip install scikit-learn`.")
    st.stop()

# ─── Model quality metrics ─────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Train MAE",
    f"{forecaster.train_mae:.1f} pax/slot",
    help="Mean absolute error on training seeds (42–46). Lower is better."
)
c2.metric(
    "Holdout MAE",
    f"{forecaster.holdout_mae:.1f} pax/slot",
    help="Mean absolute error on held-out seeds (47–52) — unseen during training. This is the honest measure of forecast quality."
)
c3.metric(
    "vs Naive forecast",
    f"{forecaster.improvement_pct:+.0f}%",
    help="Improvement in MAE vs a naive baseline (predict last slot's demand). Positive = better than naive."
)
c4.metric(
    "Training seeds",
    f"{len(forecaster.train_seeds)} seeds",
    help=f"Seeds used for training: {forecaster.train_seeds}"
)

# Honest callout if holdout > train (overfitting warning)
if forecaster.holdout_mae > forecaster.train_mae * 1.5:
    st.warning(
        f"Holdout MAE ({forecaster.holdout_mae:.1f}) is significantly higher than train MAE "
        f"({forecaster.train_mae:.1f}) — the model may be overfitting. "
        f"Consider more training data or stronger regularisation.",
        icon="⚠️",
    )

st.divider()

# ─── Forecast for a stop ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Forecast options")
    stop_choice = st.selectbox(
        "Stop to forecast",
        options=list(stops.keys()),
        format_func=lambda sid: stops[sid].name,
    )
    seed = st.session_state.get("selected_seed", 42)

selected_stop = stops[stop_choice]
st.markdown(f"### Demand forecast — {selected_stop.name}")
st.markdown(
    f"<p style='color:{NEUTRAL};font-size:13px'>"
    f"Predicted demand for the next {forecaster.horizon_steps} slots (1 slot = 15 min) · "
    f"Compared to actual simulated demand from run {seed}</p>",
    unsafe_allow_html=True
)

# Attempt forecast
try:
    forecast_df = forecaster.predict_stop(selected_stop.stop_id, seed=seed)
    if forecast_df is None or forecast_df.empty:
        st.info("Not enough historical data to forecast for this stop yet. Try a later time slot.")
    else:
        fig = go.Figure()

        if "actual" in forecast_df.columns:
            fig.add_trace(go.Scatter(
                x=[fmt_time(t) for t in forecast_df["time_min"]],
                y=forecast_df["actual"],
                mode="lines+markers",
                name="Actual demand",
                line=dict(color=SUCCESS, width=2),
                marker=dict(size=7),
                hovertemplate="<b>%{x}</b><br>Actual: %{y:.0f} pax<extra></extra>",
            ))

        if "predicted" in forecast_df.columns:
            fig.add_trace(go.Scatter(
                x=[fmt_time(t) for t in forecast_df["time_min"]],
                y=forecast_df["predicted"],
                mode="lines+markers",
                name="ML forecast",
                line=dict(color=ACCENT, width=2, dash="dash"),
                marker=dict(size=7, color=ACCENT),
                hovertemplate="<b>%{x}</b><br>Forecast: %{y:.0f} pax<extra></extra>",
            ))

        if "naive" in forecast_df.columns:
            fig.add_trace(go.Scatter(
                x=[fmt_time(t) for t in forecast_df["time_min"]],
                y=forecast_df["naive"],
                mode="lines",
                name="Naive (last slot)",
                line=dict(color=NEUTRAL, width=1.5, dash="dot"),
                hovertemplate="<b>%{x}</b><br>Naive: %{y:.0f} pax<extra></extra>",
            ))

        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(title="Time of day", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
            yaxis=dict(title="Passengers per 15-min slot", color=NEUTRAL, gridcolor="rgba(148,163,184,0.08)"),
            font=dict(color=NEUTRAL),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=NEUTRAL)),
            height=360, margin=dict(l=10, r=20, t=20, b=30),
        )
        st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.warning(f"Could not generate forecast: {e}")
    st.info("The forecaster needs at least 20 historical data points before making predictions.")

st.divider()

# ─── Model explanation ─────────────────────────────────────────────────────────
st.markdown("### How the forecast works")
st.markdown(f"""
<div style='color:{NEUTRAL};font-size:13px;line-height:1.7'>
<b style='color:#e2e8f0'>Model</b>: Gradient Boosting Regressor (scikit-learn) trained on simulated demand data.<br><br>

<b style='color:#e2e8f0'>Features used</b>:<br>
&bull; Time of day encoded as sin/cos (captures cyclical patterns like morning rush)<br>
&bull; Last 8 boarding counts at this stop (lag features)<br>
&bull; Demand multiplier at the current time (encodes peak vs. off-peak)<br>
&bull; Stop identity (ordinal encoding)<br><br>

<b style='color:#e2e8f0'>Training</b>: Seeds 42–46 (5 full simulation runs). Holdout: Seeds 47–52 (6 runs, not seen during training).<br>
Reporting holdout MAE honestly — the relevant measure of real-world performance.<br><br>

<b style='color:#e2e8f0'>Why it matters</b>: The optimizer uses the forecast to trigger proactive vehicle upgrades
before the peak hits, rather than reacting after passengers are already stranded.
</div>
""", unsafe_allow_html=True)
