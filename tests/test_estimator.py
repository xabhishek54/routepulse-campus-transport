"""
Tests for the Kalman-filter arrival estimator.
"""
import pytest
from routepulse.models import Stop, VehicleType, Vehicle, RouteStop, Route, ScheduledDeparture
from routepulse.estimator import KalmanDelayFilter, estimate_etas, check_eta_calibration


def _make_simple_dep():
    stops = [
        Stop(f"S{i}", f"Stop {i}", 51.50 + i * 0.001, -0.14, 10)
        for i in range(5)
    ]
    route_stops = []
    cumulative = 0.0
    for i, s in enumerate(stops):
        seg = 0.0 if i == 0 else 3.0
        cumulative += seg
        route_stops.append(RouteStop(s, seg, cumulative))
    route = Route("R1", "Test", route_stops)
    vt = VehicleType("small", "Mini", 25)
    v = Vehicle("V01", vt)
    dep = ScheduledDeparture("D0001", route, 480.0, v)
    return dep, stops


def test_kalman_update_reduces_uncertainty():
    kf = KalmanDelayFilter(initial_delay=0.0, initial_uncertainty=2.0)
    # After an observation, uncertainty should decrease
    _, std_before = kf.predict(1)
    kf.update(1.5)
    _, std_after = kf.predict(1)
    assert std_after < std_before, "Kalman update should reduce uncertainty"


def test_kalman_tracks_delay():
    kf = KalmanDelayFilter(initial_delay=0.0, initial_uncertainty=2.0)
    kf.update(5.0)
    delay, _ = kf.predict(0)
    assert 3.0 < delay < 6.0, f"Expected delay near 5, got {delay}"


def test_estimate_etas_returns_future_stops():
    dep, stops = _make_simple_dep()
    from routepulse.models import StopEvent
    # Simulate having visited first 2 stops with 1-min delay
    observed = [
        StopEvent(
            stop=stops[i],
            scheduled_arrival=480.0 + i * 3,
            actual_arrival=480.0 + i * 3 + 1.0,
            demand_at_stop=5,
            boarded=5,
            alighted=0,
            on_board_after=5,
            capacity=25,
            delay=1.0,
        )
        for i in range(2)
    ]
    etas = estimate_etas(dep, observed)
    assert len(etas) == 3, f"Expected 3 future stops, got {len(etas)}"
    for eta in etas:
        assert eta.uncertainty_minutes >= 0
        assert eta.lower_bound <= eta.estimated_arrival <= eta.upper_bound


def test_calibration_check():
    dep, stops = _make_simple_dep()
    from routepulse.models import StopEvent, ETAEstimate
    etas = [
        ETAEstimate(
            stop=stops[2],
            scheduled_arrival=486.0,
            estimated_arrival=487.0,
            uncertainty_minutes=2.0,
            current_delay=1.0,
        )
    ]
    # Actual falls within CI
    cal = check_eta_calibration(etas, {"S2": 487.5})
    assert cal["n_within_ci"] == 1
    assert cal["calibration"] == 1.0

    # Actual falls outside CI
    cal2 = check_eta_calibration(etas, {"S2": 492.0})
    assert cal2["n_within_ci"] == 0
    assert cal2["calibration"] == 0.0
