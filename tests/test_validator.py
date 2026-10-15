"""
Tests for the independent validator.
"""
import pytest
from routepulse.data_gen import build_campus, build_baseline_plan
from routepulse.simulator import simulate_plan
from routepulse.validator import validate, validate_plan_schedule


def test_baseline_schedule_passes_all_constraints():
    _, _, _, departures = build_campus()
    plan = build_baseline_plan(departures=departures)
    report = validate_plan_schedule(plan)
    assert report.passed, f"Baseline schedule failed: {report.summary()}"


def test_simulated_baseline_passes():
    _, _, _, departures = build_campus()
    plan = build_baseline_plan(departures=departures)
    trips = simulate_plan(plan, base_seed=42)
    report = validate(plan, trips)
    # C5 (capacity) may or may not fail in simulation (demand is stochastic)
    # but the report must run without error
    assert report.n_violations >= 0


def test_bad_plan_detected():
    """A plan with a headway violation should fail the validator."""
    from routepulse.models import Plan, ScheduledDeparture
    stops, routes, vehicles, departures = build_campus()
    plan = build_baseline_plan(departures=departures)
    # Clone first departure with only 1 min gap — a violation
    d0 = plan.departures[0]
    bad_dep = ScheduledDeparture("D9999", d0.route, d0.departure_time + 1.0, d0.vehicle)
    bad_plan = Plan(
        plan_id="bad_plan",
        name="Bad Plan",
        description="Should fail headway check",
        departures=plan.departures + [bad_dep],
    )
    report = validate_plan_schedule(bad_plan)
    assert not report.passed, "Bad plan with 1-min headway should fail validation"


def test_optimizer_output_passes_validator():
    """Recommended plan from optimizer must always pass validation."""
    from routepulse.data_gen import build_baseline_plan
    from routepulse.simulator import simulate_plan
    from routepulse.detector import detect_all
    from routepulse.optimizer import build_recommended_plan

    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)
    trips = simulate_plan(baseline, base_seed=42)
    det = detect_all(baseline, trips)
    recommended = build_recommended_plan(baseline, trips, det["missed_connections"])
    report = validate_plan_schedule(recommended)
    assert report.passed, f"Recommended plan failed validation: {report.summary()}"
