"""
Tests for routepulse.optimizer.

Verifies:
  - Actions are correctly typed and described
  - Upgrade benefit is honest (min(unmet, extra_capacity))
  - Resulting plan passes validation
  - Service rate improves vs naive baseline
  - action_summary returns consistent counts
"""
import pytest


def _setup():
    from routepulse.data_gen import build_campus, build_naive_baseline
    from routepulse.simulator import simulate_plan
    from routepulse.detector import detect_all
    stops, routes, vehicles, departures = build_campus()
    naive = build_naive_baseline(departures=departures)
    trips = simulate_plan(naive, base_seed=42)
    det = detect_all(naive, trips)
    return naive, trips, det


def test_recommended_plan_passes_validation():
    """The plan returned by build_recommended_plan must pass all constraint checks."""
    from routepulse.optimizer import build_recommended_plan
    from routepulse.validator import validate_plan_schedule
    naive, trips, det = _setup()
    plan = build_recommended_plan(naive, trips, det["missed_connections"])
    report = validate_plan_schedule(plan)
    assert report.passed, (
        f"Optimised plan failed validation: "
        + "; ".join(c.detail for c in report.checks if not c.passed)
    )


def test_vehicle_upgrades_have_honest_benefit():
    """
    passengers_accommodated for each upgrade action must equal
    min(trip.total_unmet_demand, LARGE_BUS_CAPACITY - vehicle.capacity).
    """
    from routepulse.optimizer import recommend_vehicle_upgrades
    from routepulse.config import LARGE_BUS_CAPACITY
    naive, trips, _ = _setup()
    actions, _ = recommend_vehicle_upgrades(naive, trips)
    for action in actions:
        dep = action.departure
        trip = next((t for t in trips if t.departure.departure_id == dep.departure_id), None)
        if trip is None:
            continue
        extra_cap = LARGE_BUS_CAPACITY - dep.vehicle.capacity
        expected = min(trip.total_unmet_demand, extra_cap)
        assert action.passengers_accommodated == expected, (
            f"Upgrade benefit should be {expected} but got {action.passengers_accommodated} "
            f"for {dep.departure_id}"
        )


def test_all_action_types_valid():
    """All action_type values must be one of the known types."""
    from routepulse.optimizer import build_recommended_plan
    naive, trips, det = _setup()
    plan = build_recommended_plan(naive, trips, det["missed_connections"])
    valid_types = {"vehicle_upgrade", "extra_trip", "departure_shift"}
    for action in plan.actions_applied:
        assert action.action_type in valid_types, f"Unknown action type: {action.action_type}"


def test_no_upgrades_exceed_max_swaps():
    """Total vehicle upgrades must not exceed MAX_SWAPS config limit."""
    from routepulse.optimizer import recommend_vehicle_upgrades
    from routepulse.config import MAX_SWAPS
    naive, trips, _ = _setup()
    actions, _ = recommend_vehicle_upgrades(naive, trips)
    assert len(actions) <= MAX_SWAPS


def test_action_summary_consistent():
    """action_summary counts must match actual action counts."""
    from routepulse.optimizer import build_recommended_plan, action_summary
    naive, trips, det = _setup()
    plan = build_recommended_plan(naive, trips, det["missed_connections"])
    summary = action_summary(plan.actions_applied)
    assert summary["vehicle_upgrades"] == sum(1 for a in plan.actions_applied if a.action_type == "vehicle_upgrade")
    assert summary["extra_trips"] == sum(1 for a in plan.actions_applied if a.action_type == "extra_trip")
    assert summary["departure_shifts"] == sum(1 for a in plan.actions_applied if a.action_type == "departure_shift")
    assert summary["total_actions"] == len(plan.actions_applied)


def test_service_rate_improves_vs_naive():
    """RoutePulse service_rate should be >= naive baseline service_rate."""
    from routepulse.optimizer import build_recommended_plan
    from routepulse.simulator import simulate_plan
    from routepulse.evaluator import compute_metrics
    naive, trips_n, det = _setup()
    plan = build_recommended_plan(naive, trips_n, det["missed_connections"])
    trips_o = simulate_plan(plan, base_seed=42)
    m_n = compute_metrics(naive, trips_n, 42)
    m_o = compute_metrics(plan, trips_o, 42)
    assert m_o["service_rate"] >= m_n["service_rate"] - 0.01, (
        f"Optimised service_rate {m_o['service_rate']:.3f} should be >= "
        f"naive {m_n['service_rate']:.3f}"
    )
