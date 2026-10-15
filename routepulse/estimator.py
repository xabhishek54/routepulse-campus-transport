"""
Arrival-window estimator for RoutePulse.

Uses a 1D Kalman filter to propagate delay uncertainty along a route.
Given observed delays at visited stops, estimates delay (and confidence
interval) at all remaining stops.

All Kalman parameters are drawn from routepulse.config — not hardcoded here.
"""
from __future__ import annotations
import math
from typing import List, Optional

from routepulse.config import (
    KALMAN_INITIAL_UNCERTAINTY,
    KALMAN_PROCESS_NOISE,
    KALMAN_OBS_NOISE,
    ETA_CI_PCT,
)
from routepulse.models import (
    ScheduledDeparture, StopEvent, ETAEstimate,
)


# ---------------------------------------------------------------------------
# Kalman filter state
# ---------------------------------------------------------------------------
class KalmanDelayFilter:
    """
    Tracks and predicts bus delay as it propagates along a route.

    State  x = current delay estimate (minutes)
    Covariance P = uncertainty in delay estimate (minutes²)
    """

    def __init__(
        self,
        initial_delay: float = 0.0,
        initial_uncertainty: float = KALMAN_INITIAL_UNCERTAINTY,
        process_noise_per_stop: float = KALMAN_PROCESS_NOISE,
        observation_noise: float = KALMAN_OBS_NOISE,
    ):
        self.x = initial_delay
        self.P = initial_uncertainty ** 2
        self.Q = process_noise_per_stop ** 2
        self.R = observation_noise ** 2

    def predict(self, n_stops_ahead: int = 1) -> tuple[float, float]:
        """Return (predicted_delay_minutes, uncertainty_std) n stops ahead."""
        P_pred = self.P + n_stops_ahead * self.Q
        return self.x, math.sqrt(P_pred)

    def update(self, observed_delay: float) -> None:
        """Incorporate a new delay observation at the current stop."""
        K = self.P / (self.P + self.R)
        self.x = self.x + K * (observed_delay - self.x)
        self.P = (1 - K) * self.P
        self.P = max(self.P, self.Q)  # floor at process noise

    def update_and_predict(
        self, observed_delay: float, n_stops_ahead: int = 1
    ) -> tuple[float, float]:
        self.update(observed_delay)
        return self.predict(n_stops_ahead)


# ---------------------------------------------------------------------------
# ETA estimation for a trip in progress
# ---------------------------------------------------------------------------
def estimate_etas(
    departure: ScheduledDeparture,
    observed_stop_events: List[StopEvent],
    confidence_pct: float = ETA_CI_PCT,
) -> List[ETAEstimate]:
    """
    Given observed StopEvents and the scheduled departure, estimate arrival
    times at all remaining stops with uncertainty.

    confidence_pct: CI coverage (e.g. 90.0 → z ≈ 1.645).
    """
    from scipy import stats
    alpha = 1 - confidence_pct / 100.0
    z = stats.norm.ppf(1 - alpha / 2)

    observed_stop_ids = {ev.stop.stop_id for ev in observed_stop_events}
    route = departure.route

    kf = KalmanDelayFilter()
    last_observed_delay = 0.0

    for ev in observed_stop_events:
        kf.update(ev.delay)
        last_observed_delay = ev.delay

    estimates = []
    stops_ahead = 0

    for rs in route.route_stops:
        if rs.stop.stop_id in observed_stop_ids:
            continue
        stops_ahead += 1
        pred_delay, pred_std = kf.predict(stops_ahead)
        scheduled_arr = departure.scheduled_arrival_at(rs.stop.stop_id)
        if scheduled_arr is None:
            continue

        estimated_arr = scheduled_arr + pred_delay
        half_width = z * pred_std

        estimates.append(ETAEstimate(
            stop=rs.stop,
            scheduled_arrival=scheduled_arr,
            estimated_arrival=round(estimated_arr, 2),
            uncertainty_minutes=round(half_width, 2),
            current_delay=round(last_observed_delay, 2),
            confidence_pct=confidence_pct,
        ))

    return estimates


# ---------------------------------------------------------------------------
# Calibration check
# ---------------------------------------------------------------------------
def check_eta_calibration(
    eta_estimates: List[ETAEstimate],
    actual_arrivals: dict,
) -> dict:
    """
    Check whether actual arrivals fell within the predicted confidence intervals.

    Returns:
        n_checks, n_within_ci, calibration (fraction), mae_minutes
    """
    n_checks = 0
    n_within = 0
    total_abs_err = 0.0

    for eta in eta_estimates:
        actual = actual_arrivals.get(eta.stop.stop_id)
        if actual is None:
            continue
        n_checks += 1
        if eta.lower_bound <= actual <= eta.upper_bound:
            n_within += 1
        total_abs_err += abs(eta.estimated_arrival - actual)

    calibration = n_within / n_checks if n_checks > 0 else 0.0
    mae = total_abs_err / n_checks if n_checks > 0 else 0.0
    return {
        "n_checks": n_checks,
        "n_within_ci": n_within,
        "calibration": calibration,
        "mae_minutes": mae,
    }


# ---------------------------------------------------------------------------
# Bulk ETA evaluation over all trips
# ---------------------------------------------------------------------------
def evaluate_eta_over_trips(simulated_trips) -> dict:
    """
    For each trip, treat the first half of stops as observed and estimate
    the second half, then compare to actual arrivals.
    """
    total_mae = 0.0
    total_n = 0
    within_ci = 0

    for trip in simulated_trips:
        events = trip.stop_events
        n = len(events)
        if n < 2:
            continue
        split = max(1, n // 2)
        observed = events[:split]
        future = events[split:]

        estimates = estimate_etas(trip.departure, observed)
        future_actuals = {ev.stop.stop_id: ev.actual_arrival for ev in future}

        cal = check_eta_calibration(estimates, future_actuals)
        total_mae += cal["mae_minutes"] * cal["n_checks"]
        within_ci += cal["n_within_ci"]
        total_n += cal["n_checks"]

    return {
        "eta_mae_minutes": round(total_mae / total_n, 3) if total_n else 0.0,
        "eta_calibration": round(within_ci / total_n, 3) if total_n else 0.0,
        "n_evaluated": total_n,
    }
