"""
Tests for violation detector.
"""
import pytest
from routepulse.data_gen import build_campus, build_baseline_plan
from routepulse.simulator import simulate_plan
from routepulse.detector import detect_overcrowding, detect_schedule_conflicts, detect_all


def test_no_schedule_conflicts_in_baseline():
    _, _, _, departures = build_campus()
    plan = build_baseline_plan(departures=departures)
    conflicts = detect_schedule_conflicts(plan)
    assert len(conflicts) == 0, f"Expected no conflicts in baseline, got {conflicts}"


def test_overcrowding_detection():
    from routepulse.models import Stop, StopEvent, SimulatedTrip, ScheduledDeparture, RouteStop, Route, VehicleType, Vehicle
    s = Stop("S1", "A", 51.50, -0.14, 10)
    rs = RouteStop(s, 0.0, 0.0)
    route = Route("R1", "T", [rs])
    vt = VehicleType("small", "Mini", 25)
    v = Vehicle("V01", vt)
    dep = ScheduledDeparture("D0001", route, 480.0, v)
    # Manufacture an overcrowded stop event
    ev = StopEvent(
        stop=s,
        scheduled_arrival=480.0,
        actual_arrival=480.0,
        demand_at_stop=30,
        boarded=26,
        alighted=0,
        on_board_after=26,  # > capacity of 25
        capacity=25,
        delay=0.0,
    )
    trip = SimulatedTrip(departure=dep, stop_events=[ev], seed=42)
    violations = detect_overcrowding([trip])
    assert len(violations) == 1
    assert violations[0].violation_type == "overcrowding"


def test_simulation_and_detection_run():
    _, _, _, departures = build_campus()
    plan = build_baseline_plan(departures=departures)
    trips = simulate_plan(plan, base_seed=42)
    assert len(trips) > 0
    result = detect_all(plan, trips)
    assert "summary" in result
    assert "overcrowding_events" in result["summary"]
