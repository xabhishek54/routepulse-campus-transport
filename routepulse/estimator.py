"""
Kalman-filter ETA estimator for RoutePulse.

Model: delay propagates along a route as a random walk.
  x_k = x_{k-1} + w_k,   w_k ~ N(0, Q)   (process noise per stop)
  z_k = x_k + v_k,       v_k ~ N(0, R)   (observation noise)

Parameters are in config.py and calibrated to produce the stated CI coverage:
  - If CI is 90%, ~90% of actual arrivals should fall inside the interval.
  - ETA calibration is measured across many trips and seeds and reported honestly.

Calibration check: if actual calibration deviates by more than ±10pp from
the stated CI (e.g. 80%–100% for a 90% CI), the estimates are flagged.
"""
from __future__ import annotations
import math
from typing import List, Optional

from routepulse.config import (
    KALMAN_INITIAL_UNCERTAINTY,
    KALMAN_PROCESS_NOISE,
    KALMAN_OBS_NOISE,
    ETA_CI_PCT,
    ETA_CALIBRATION_TARGET,
    ETA_CALIBRATION_TOLERANCE,
)
from routepulse.models import ScheduledDeparture, StopEvent, ETAEstimate


# ---------------------------------------------------------------------------
# Kalman filter
# ---------------------------------------------------------------------------

class KalmanDelayFilter:
    """
    1D Kalman filter tracking delay as it evolves along a route.

    State  x = current delay estimate (minutes, positive = late)
    P      = uncertainty variance (minutes²)
    Q      = process noise variance per stop (delay can drift)
    R      = observation noise variance (GPS/AVL precision)
    """

    def __init__(
        self,
        initial_delay: float = 0.0,
        initial_uncertainty: float = KALMAN_INITIAL_UNCERTAINTY,
        process_noise_per_stop: float = KALMAN_PROCESS_NOISE,
        observation_noise: float = KALMAN_OBS_NOISE,
    ):
        self.x = initial_delay
        self.P = initial_uncertainty ** 2          # variance
        self.Q = process_noise_per_stop ** 2       # per-stop process noise variance
        self.R = observation_noise ** 2            # observation noise variance

    def update(self, observed_delay: float) -> None:
        """Incorporate a new delay observation at the current stop."""
        # Innovation
        K = self.P / (self.P + self.R)
        self.x = self.x + K * (observed_delay - self.x)
        self.P = (1 - K) * self.P
        self.P = max(self.P, self.Q)  # floor: uncertainty can't go below process noise

    def predict(self, n_stops_ahead: int = 1) -> tuple[float, float]:
        """
        Return (mean_delay_estimate, std_dev) n stops ahead.
        Uncertainty grows with distance: P_pred = P + n * Q.
        """
        P_pred = self.P + n_stops_ahead * self.Q
        return self.x, math.sqrt(P_pred)


# ---------------------------------------------------------------------------
# ETA estimation for a trip in progress
# ---------------------------------------------------------------------------

def estimate_etas(
    departure: ScheduledDeparture,
    observed_stop_events: List[StopEvent],
    confidence_pct: float = ETA_CI_PCT,
) -> List[ETAEstimate]:
    """
    Given observed StopEvents so far, estimate arrival times at remaining stops.

    Uses the position-based approach to handle loop routes correctly.
    Returns ETAEstimate for each future stop, with half-width = z * std.
    """
    from scipy import stats
    alpha = 1 - confidence_pct / 100.0
    z = stats.norm.ppf(1 - alpha / 2)

    # Build set of observed positions (not stop IDs, to handle loops)
    observed_count = len(observed_stop_events)
    kf = KalmanDelayFilter()

    for ev in observed_stop_events:
        kf.update(ev.delay)

    estimates = []
    route = departure.route

    for pos in range(observed_count, len(route.route_stops)):
        rs = route.route_stops[pos]
        stops_ahead = pos - observed_count + 1
        pred_delay, pred_std = kf.predict(stops_ahead)

        scheduled_arr = departure.scheduled_arrival_at_position(pos)
        if scheduled_arr is None:
            continue

        estimated_arr = scheduled_arr + pred_delay
        half_width = z * pred_std

        estimates.append(ETAEstimate(
            stop=rs.stop,
            scheduled_arrival=scheduled_arr,
            estimated_arrival=round(estimated_arr, 2),
            uncertainty_minutes=round(half_width, 2),
            current_delay=round(kf.x, 2),
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
        n_checks, n_within_ci, calibration (fraction), mae_minutes,
        is_well_calibrated (bool), calibration_gap
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
    target = ETA_CALIBRATION_TARGET
    gap = calibration - target
    is_good = abs(gap) <= ETA_CALIBRATION_TOLERANCE

    return {
        "n_checks": n_checks,
        "n_within_ci": n_within,
        "calibration": calibration,
        "mae_minutes": mae,
        "target": target,
        "calibration_gap_pp": round(gap * 100, 1),
        "is_well_calibrated": is_good,
    }


# ---------------------------------------------------------------------------
# Bulk calibration over all trips (proper evaluation)
# ---------------------------------------------------------------------------

def evaluate_eta_over_trips(simulated_trips) -> dict:
    """
    Proper ETA calibration: for each trip, use first half as observed,
    estimate second half, compare to actuals.

    Returns aggregate calibration and MAE across all trips.
    Calibration is meaningful only when n_evaluated is large (>= 100).
    """
    total_mae_sum = 0.0
    total_n = 0
    within_ci = 0

    for trip in simulated_trips:
        events = trip.stop_events
        n = len(events)
        if n < 3:
            continue
        split = max(1, n // 2)
        observed = events[:split]
        future = events[split:]

        estimates = estimate_etas(trip.departure, observed)
        future_actuals = {ev.stop.stop_id: ev.actual_arrival for ev in future}

        cal = check_eta_calibration(estimates, future_actuals)
        total_mae_sum += cal["mae_minutes"] * cal["n_checks"]
        within_ci += cal["n_within_ci"]
        total_n += cal["n_checks"]

    calibration = within_ci / total_n if total_n > 0 else 0.0
    mae = total_mae_sum / total_n if total_n > 0 else 0.0
    target = ETA_CALIBRATION_TARGET
    gap_pp = (calibration - target) * 100

    return {
        "eta_mae_minutes": round(mae, 3),
        "eta_calibration": round(calibration, 3),
        "eta_calibration_gap_pp": round(gap_pp, 1),
        "eta_is_well_calibrated": abs(gap_pp) <= ETA_CALIBRATION_TOLERANCE * 100,
        "n_evaluated": total_n,
    }
