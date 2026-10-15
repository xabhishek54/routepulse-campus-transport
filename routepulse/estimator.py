"""
Arrival-window estimator for RoutePulse.

Uses a simple 1D Kalman filter to estimate delay propagation along a route.
Given the observed delay at the current stop, it estimates the delay (and
uncertainty) at future stops.

State: [delay] (scalar)
Observation: actual delay at a stop
Process noise: delay grows ~0.5 min/stop (traffic uncertainty compounds)
Observation noise: GPS position uncertainty ~0.3 min

The filter is intentionally simple and explainable — no black boxes.
"""
from __future__ import annotations
import math
from typing import List, Optional

from routepulse.models import (
    ScheduledDeparture, StopEvent, ETAEstimate, Stop,
)


# ---------------------------------------------------------------------------
# Kalman filter state
# ---------------------------------------------------------------------------
class KalmanDelayFilter:
    """
    Tracks and predicts bus delay as it propagates along a route.

    State: x = current delay estimate (minutes)
    Covariance: P = uncertainty in delay estimate (minutes^2)
    """

    def __init__(
        self,
        initial_delay: float = 0.0,
        initial_uncertainty: float = 1.0,
        process_noise_per_stop: float = 0.25,   # Q: delay grows by this^2 per stop
        observation_noise: float = 0.3,          # R: GPS/timing measurement noise (min)
    ):
        self.x = initial_delay         # state: delay estimate
        self.P = initial_uncertainty ** 2  # covariance
        self.Q = process_noise_per_stop ** 2
        self.R = observation_noise ** 2

    def predict(self, n_stops_ahead: int = 1) -> tuple[float, float]:
        """Return (predicted_delay, uncertainty_std) after n_stops_ahead."""
        P_pred = self.P + n_stops_ahead * self.Q
        return self.x, math.sqrt(P_pred)

    def update(self, observed_delay: float) -> None:
        """Incorporate a new delay observation at the current stop."""
        # Kalman gain
        K = self.P / (self.P + self.R)
        self.x = self.x + K * (observed_delay - self.x)
        self.P = (1 - K) * self.P
        # Ensure covariance doesn't go below process noise floor
        self.P = max(self.P, self.Q)

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
    confidence_pct: float = 90.0,
) -> List[ETAEstimate]:
    """
    Given observed StopEvents (already visited stops) and the scheduled departure,
    estimate arrival times at all remaining stops with uncertainty.

    Returns a list of ETAEstimate for every unvisited stop.

    confidence_pct: CI coverage (90% by default → z ≈ 1.645)
    """
    # z-score for one-sided CI half-width
    from scipy import stats  # type: ignore
    alpha = 1 - confidence_pct / 100.0
    z = stats.norm.ppf(1 - alpha / 2)

    observed_stop_ids = {ev.stop.stop_id for ev in observed_stop_events}
    route = departure.route

    # Build Kalman filter from observed delays
    kf = KalmanDelayFilter(initial_delay=0.0, initial_uncertainty=2.0)
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
    actual_arrivals: dict,  # stop_id -> actual arrival time (min)
) -> dict:
    """
    Check whether actual arrivals fell within the predicted confidence intervals.

    Returns:
        {
            "n_checks": int,
            "n_within_ci": int,
            "calibration": float,   # fraction within CI
            "mae_minutes": float,   # mean absolute error of point estimates
        }
    """
    n_checks = 0
    n_within = 0
    total_abs_err = 0.0

    for eta in eta_estimates:
        actual = actual_arrivals.get(eta.stop.stop_id)
        if actual is None:
            continue
        n_checks += 1
        in_ci = eta.lower_bound <= actual <= eta.upper_bound
        if in_ci:
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
    For each trip, treat the first half of stops as "observed" and estimate
    the second half, then compare to actual arrivals.

    Returns aggregated calibration and MAE.
    """
    from routepulse.models import SimulatedTrip  # avoid circular at top

    all_estimates: List[ETAEstimate] = []
    actual_map: dict = {}
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
