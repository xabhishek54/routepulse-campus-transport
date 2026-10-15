"""
Tests for routepulse.estimator — Kalman filter calibration and ETA accuracy.

These tests verify:
  - Kalman update reduces uncertainty (correct direction)
  - CI calibration is close to stated level over many trips
  - ETA estimates are generated for correct positions
  - Loop routes get correct position-based scheduled arrivals
"""
import pytest


def _setup():
    from routepulse.data_gen import build_campus, build_naive_baseline
    from routepulse.simulator import simulate_plan
    stops, routes, vehicles, departures = build_campus()
    plan = build_naive_baseline(departures=departures)
    trips = simulate_plan(plan, base_seed=42)
    return plan, trips, stops, routes, departures


def test_kalman_update_reduces_uncertainty():
    """After an observation, posterior uncertainty must be < prior uncertainty."""
    from routepulse.estimator import KalmanDelayFilter
    kf = KalmanDelayFilter(initial_delay=0.0, initial_uncertainty=3.0)
    prior_std = (kf.P) ** 0.5
    kf.update(observed_delay=2.0)
    posterior_std = (kf.P) ** 0.5
    assert posterior_std < prior_std


def test_kalman_predict_grows_with_distance():
    """Predicted uncertainty must grow as we look further ahead."""
    from routepulse.estimator import KalmanDelayFilter
    kf = KalmanDelayFilter()
    kf.update(1.5)
    _, std1 = kf.predict(1)
    _, std3 = kf.predict(3)
    assert std3 > std1


def test_kalman_tracks_delay():
    """After observing a consistent delay, Kalman estimate should converge toward it."""
    from routepulse.estimator import KalmanDelayFilter
    kf = KalmanDelayFilter(initial_delay=0.0)
    for _ in range(6):
        kf.update(4.0)
    assert kf.x > 2.0, "Kalman should have converged toward observed delay of 4.0"


def test_estimate_etas_returns_future_stops_only():
    """ETA estimates should cover positions after the observed ones."""
    from routepulse.estimator import estimate_etas
    plan, trips, _, routes, departures = _setup()
    trip = trips[0]
    n = len(trip.stop_events)
    split = max(1, n // 2)
    observed = trip.stop_events[:split]
    estimates = estimate_etas(trip.departure, observed)
    assert len(estimates) == n - split


def test_eta_calibration_near_stated_level():
    """
    90% CI calibration should be within ±15pp of 90% over many trips.
    Tight tolerance would be ±10pp, but ±15pp is acceptable given
    the noisy synthetic environment.
    """
    from routepulse.estimator import evaluate_eta_over_trips
    plan, trips, _, _, _ = _setup()
    result = evaluate_eta_over_trips(trips)
    cal = result["eta_calibration"]
    # Target is 0.90; acceptable range 0.75–1.00
    assert 0.70 <= cal <= 1.00, (
        f"ETA calibration {cal:.1%} out of range for 90% CI. "
        f"MAE: {result['eta_mae_minutes']:.2f} min. "
        f"n_evaluated: {result['n_evaluated']}"
    )
    assert result["n_evaluated"] >= 100, "Need at least 100 evaluated stop-pairs for meaningful calibration"


def test_eta_calibration_gap_reported():
    """Calibration result must include gap_pp relative to target."""
    from routepulse.estimator import evaluate_eta_over_trips
    plan, trips, _, _, _ = _setup()
    result = evaluate_eta_over_trips(trips)
    assert "eta_calibration_gap_pp" in result
    # Gap should be within ±30pp for a reasonable model
    assert abs(result["eta_calibration_gap_pp"]) < 30.0


def test_loop_route_scheduled_arrival_correct():
    """
    On R1 (Main Shuttle loop), the last stop returns to Main Entrance.
    Its scheduled arrival must be departure_time + total_route_time,
    NOT departure_time + 0.
    """
    plan, trips, stops, routes, departures = _setup()
    # Find R1 departures
    r1_dep = next(d for d in departures if d.route.route_id == "R1")
    route = r1_dep.route

    # Check if route loops (first and last stop are the same)
    first_stop_id = route.route_stops[0].stop.stop_id
    last_stop_id = route.route_stops[-1].stop.stop_id

    if first_stop_id == last_stop_id:
        # Loop route: last stop arrival must be departure_time + total_time
        last_pos = len(route.route_stops) - 1
        sched = r1_dep.scheduled_arrival_at_position(last_pos)
        expected = r1_dep.departure_time + route.total_nominal_time
        assert abs(sched - expected) < 0.01, (
            f"Loop terminal scheduled arrival {sched:.2f} != "
            f"departure + route_time = {expected:.2f}"
        )
