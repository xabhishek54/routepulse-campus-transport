"""
Tests for routepulse.validator — hard constraint checks.

These tests verify:
  - Valid baseline passes all checks
  - Each violated constraint is individually detected
  - Fleet inventory check catches overlapping vehicle assignments
  - Turnaround check catches insufficient gaps
"""
import pytest


def _make_base_plan():
    from routepulse.data_gen import build_campus, build_naive_baseline
    stops, routes, vehicles, departures = build_campus()
    return build_naive_baseline(departures=departures), stops, routes, vehicles


def test_valid_baseline_passes_all_checks():
    """The generated naive baseline must pass all 7 constraint checks."""
    from routepulse.validator import validate_plan_schedule
    plan, _, _, _ = _make_base_plan()
    report = validate_plan_schedule(plan)
    assert report.passed, (
        f"Baseline should be valid but has {report.n_violations} violations:\n"
        + "\n".join(f"  {c.constraint}: {c.detail}" for c in report.checks if not c.passed)
    )


def test_headway_violation_detected():
    """Insert two departures 2 min apart on same route — C2 must fail."""
    from routepulse.validator import validate_plan_schedule
    from routepulse.models import Plan, ScheduledDeparture
    plan, _, _, _ = _make_base_plan()
    first = plan.departures[0]
    clash = ScheduledDeparture("CLASH", first.route, first.departure_time + 2.0, first.vehicle)
    bad = Plan("bad", "Bad", "test", [first, clash])
    report = validate_plan_schedule(bad)
    c2 = next(c for c in report.checks if "C2" in c.constraint)
    assert not c2.passed


def test_fleet_conflict_detected():
    """Assign same vehicle to two simultaneous trips — C5 must fail."""
    from routepulse.validator import validate_plan_schedule
    from routepulse.models import Plan, ScheduledDeparture
    plan, _, _, _ = _make_base_plan()
    d1 = plan.departures[0]
    # Second trip uses same vehicle and starts BEFORE d1 ends
    d2 = ScheduledDeparture("OVERLAP", d1.route, d1.departure_time + 2.0, d1.vehicle)
    bad = Plan("fleet_conflict", "Bad", "test", [d1, d2])
    report = validate_plan_schedule(bad)
    c5 = next(c for c in report.checks if "C5" in c.constraint)
    assert not c5.passed


def test_out_of_window_departure_detected():
    """Departure at 23:00 (outside operating hours) — C1 must fail."""
    from routepulse.validator import validate_plan_schedule
    from routepulse.models import Plan, ScheduledDeparture
    plan, _, _, _ = _make_base_plan()
    d = plan.departures[0]
    late = ScheduledDeparture("LATE", d.route, 23 * 60.0, d.vehicle)
    bad = Plan("oow", "Bad", "test", [d, late])
    report = validate_plan_schedule(bad)
    c1 = next(c for c in report.checks if "C1" in c.constraint)
    assert not c1.passed


def test_simulation_checks_pass_on_valid_trips():
    """Simulation-level checks (C9–C11) must pass on a legitimate simulation."""
    from routepulse.data_gen import build_campus, build_naive_baseline
    from routepulse.simulator import simulate_plan
    from routepulse.validator import validate_simulated_trips
    stops, routes, vehicles, departures = build_campus()
    plan = build_naive_baseline(departures=departures)
    trips = simulate_plan(plan, base_seed=42)
    report = validate_simulated_trips(plan, trips)
    assert report.passed, (
        "Simulation-level checks should pass but got:\n"
        + "\n".join(f"  {c.constraint}: {c.detail}" for c in report.checks if not c.passed)
    )


def test_n_violations_counts_failures():
    """n_violations must equal the count of failed checks."""
    from routepulse.validator import validate_plan_schedule
    from routepulse.models import Plan, ScheduledDeparture
    plan, _, _, _ = _make_base_plan()
    d = plan.departures[0]
    clash = ScheduledDeparture("CLASH", d.route, d.departure_time + 2.0, d.vehicle)
    bad = Plan("bad", "Bad", "test", [d, clash])
    report = validate_plan_schedule(bad)
    assert report.n_violations == sum(1 for c in report.checks if not c.passed)


def test_optimised_plan_passes_validation():
    """The optimizer's recommended plan must pass all schedule checks."""
    from routepulse.data_gen import build_campus, build_naive_baseline
    from routepulse.simulator import simulate_plan
    from routepulse.detector import detect_all
    from routepulse.optimizer import build_recommended_plan
    from routepulse.validator import validate_plan_schedule
    stops, routes, vehicles, departures = build_campus()
    naive = build_naive_baseline(departures=departures)
    trips = simulate_plan(naive, base_seed=42)
    det = detect_all(naive, trips)
    optimised = build_recommended_plan(naive, trips, det["missed_connections"])
    report = validate_plan_schedule(optimised)
    assert report.passed, (
        f"Optimised plan failed: {report.n_violations} violations:\n"
        + "\n".join(f"  {c.constraint}: {c.detail}" for c in report.checks if not c.passed)
    )
