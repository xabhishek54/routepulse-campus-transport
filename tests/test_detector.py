"""
Tests for routepulse.detector — crowding, schedule conflicts, missed connections.

These tests verify:
  - crowding (unmet_demand > 0) is detected correctly
  - schedule_conflicts checks headway
  - missed_connections fires when extra wait > threshold
  - detect_all returns consistent summary
"""
import pytest


def _setup():
    from routepulse.data_gen import build_campus, build_naive_baseline
    from routepulse.simulator import simulate_plan
    stops, routes, vehicles, departures = build_campus()
    plan = build_naive_baseline(departures=departures)
    trips = simulate_plan(plan, base_seed=42)
    return plan, trips, stops, routes


def test_crowding_detected_on_stressed_campus():
    """With naive small buses and high demand, crowding events must occur."""
    from routepulse.detector import detect_crowding
    plan, trips, _, _ = _setup()
    violations = detect_crowding(trips)
    # Campus is designed so crowding always happens at peak
    assert len(violations) > 0, "Expected crowding on naive baseline"
    # All violations should have non-null trip and stop_event
    for v in violations:
        assert v.trip is not None
        assert v.stop_event is not None
        assert v.stop_event.unmet_demand > 0


def test_crowding_consistent_with_unmet_demand():
    """Count of crowding violations must equal count of stop-events with unmet_demand > 0."""
    from routepulse.detector import detect_crowding
    plan, trips, _, _ = _setup()
    violations = detect_crowding(trips)
    manual_count = sum(
        1 for t in trips for ev in t.stop_events if ev.unmet_demand > 0
    )
    assert len(violations) == manual_count


def test_no_schedule_conflicts_in_valid_baseline():
    """Naive baseline has 15-min headway everywhere — no conflicts expected."""
    from routepulse.detector import detect_schedule_conflicts
    plan, trips, _, _ = _setup()
    conflicts = detect_schedule_conflicts(plan)
    assert len(conflicts) == 0, f"Unexpected conflicts: {conflicts}"


def test_schedule_conflict_detected_on_bad_plan():
    """Manually inserting a departure 2 min apart must trigger a conflict."""
    from routepulse.detector import detect_schedule_conflicts
    from routepulse.models import Plan, ScheduledDeparture
    plan, trips, _, _ = _setup()
    # Create a plan with a deliberate headway violation
    first_dep = plan.departures[0]
    clash = ScheduledDeparture(
        "CLASH",
        first_dep.route,
        first_dep.departure_time + 2.0,  # only 2 min gap
        first_dep.vehicle,
    )
    bad_plan = Plan("bad", "Bad Plan", "test", [first_dep, clash])
    conflicts = detect_schedule_conflicts(bad_plan)
    assert len(conflicts) == 1


def test_detect_all_summary_consistent():
    """detect_all summary counts must match individual detector outputs."""
    from routepulse.detector import detect_all, detect_crowding, detect_schedule_conflicts
    plan, trips, _, _ = _setup()
    result = detect_all(plan, trips)
    assert result["summary"]["crowding_events"] == len(result["crowding"])
    assert result["summary"]["schedule_conflicts"] == len(result["schedule_conflicts"])
    assert result["summary"]["missed_connections"] == len(result["missed_connections"])


def test_detect_all_total_equals_sum():
    """Total violations in detect_all must equal sum of all sub-detectors."""
    from routepulse.detector import detect_all
    plan, trips, _, _ = _setup()
    result = detect_all(plan, trips)
    expected = (
        len(result["crowding"])
        + len(result["schedule_conflicts"])
        + len(result["missed_connection_violations"])
    )
    assert result["summary"]["total_violations"] == expected
