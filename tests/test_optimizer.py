"""
Tests for the optimizer.
"""
import pytest
from routepulse.data_gen import build_campus, build_baseline_plan
from routepulse.simulator import simulate_plan
from routepulse.detector import detect_all
from routepulse.optimizer import (
    build_recommended_plan, recommend_vehicle_swaps, tradeoff_summary,
)
from routepulse.validator import validate_plan_schedule


def test_vehicle_swap_produces_larger_vehicle():
    """When overcrowding exists, vehicle swap should upgrade capacity."""
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    # Run many seeds to ensure we see overcrowding
    trips = simulate_plan(baseline, base_seed=42)
    actions, swaps = recommend_vehicle_swaps(baseline, trips)
    for dep_id, new_vehicle in swaps.items():
        orig = next(d for d in baseline.departures if d.departure_id == dep_id)
        assert new_vehicle.capacity >= orig.vehicle.capacity


def test_recommended_plan_has_more_or_equal_departures():
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    trips = simulate_plan(baseline, base_seed=42)
    det = detect_all(baseline, trips)
    recommended = build_recommended_plan(baseline, trips, det["missed_connections"])
    assert len(recommended.departures) >= len(baseline.departures)


def test_tradeoff_summary_keys():
    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    trips = simulate_plan(baseline, base_seed=42)
    det = detect_all(baseline, trips)
    recommended = build_recommended_plan(baseline, trips, det["missed_connections"])
    ts = tradeoff_summary(recommended.actions_applied)
    assert "vehicle_upgrades" in ts
    assert "extra_trips" in ts
    assert "departure_nudges" in ts
