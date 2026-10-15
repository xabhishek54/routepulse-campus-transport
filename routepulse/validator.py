"""
Independent hard-constraint validator for RoutePulse.

All threshold constants come from routepulse.config.
This module is fully separate from the optimizer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

from routepulse.config import MIN_HEADWAY, OP_START, OP_END
from routepulse.models import Plan, SimulatedTrip


@dataclass
class ConstraintCheck:
    constraint: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    plan_id: str
    checks: List[ConstraintCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def n_violations(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] Plan '{self.plan_id}': "
            f"{self.n_violations}/{len(self.checks)} constraint checks failed"
        )


def validate_plan_schedule(plan: Plan) -> ValidationReport:
    """Check schedule constraints without running simulation."""
    report = ValidationReport(plan_id=plan.plan_id)

    by_route: dict[str, list] = {}
    for dep in plan.departures:
        by_route.setdefault(dep.route.route_id, []).append(dep)

    # C1: Operating window
    oow_issues = [
        dep.departure_id for dep in plan.departures
        if dep.departure_time < OP_START or dep.departure_time > OP_END
    ]
    report.checks.append(ConstraintCheck(
        constraint="C1: All departures within operating window",
        passed=len(oow_issues) == 0,
        detail=(
            f"{len(oow_issues)} departures outside "
            f"{OP_START//60:02d}:00–{OP_END//60:02d}:00"
            if oow_issues else "All departures within window"
        ),
    ))

    # C2: Minimum headway per route
    headway_issues = []
    for rid, deps in by_route.items():
        deps_sorted = sorted(deps, key=lambda d: d.departure_time)
        for i in range(len(deps_sorted) - 1):
            gap = deps_sorted[i + 1].departure_time - deps_sorted[i].departure_time
            if gap < MIN_HEADWAY:
                headway_issues.append(
                    f"Route {rid}: {deps_sorted[i].departure_id}/"
                    f"{deps_sorted[i+1].departure_id} gap={gap:.1f}min"
                )
    report.checks.append(ConstraintCheck(
        constraint=f"C2: Minimum headway ≥ {MIN_HEADWAY:.0f} min per route",
        passed=len(headway_issues) == 0,
        detail="; ".join(headway_issues) if headway_issues else "All headways OK",
    ))

    # C3: No duplicate departure times on same route
    dup_issues = []
    for rid, deps in by_route.items():
        seen: set = set()
        for d in deps:
            if d.departure_time in seen:
                dup_issues.append(f"Route {rid} time {d.departure_time}")
            seen.add(d.departure_time)
    report.checks.append(ConstraintCheck(
        constraint="C3: No duplicate departure times on same route",
        passed=len(dup_issues) == 0,
        detail="; ".join(dup_issues) if dup_issues else "No duplicates",
    ))

    # C4: Every route has at least one departure
    empty_routes = [rid for rid in by_route if len(by_route[rid]) == 0]
    report.checks.append(ConstraintCheck(
        constraint="C4: Every route has at least one departure",
        passed=len(empty_routes) == 0,
        detail=f"Empty routes: {empty_routes}" if empty_routes else "All routes served",
    ))

    return report


def validate_simulated_trips(
    plan: Plan, trips: List[SimulatedTrip]
) -> ValidationReport:
    """Check simulation-level hard constraints."""
    report = ValidationReport(plan_id=plan.plan_id + "_sim")

    # C5: Capacity never exceeded
    cap_violations = []
    for trip in trips:
        for ev in trip.stop_events:
            if ev.on_board_after > ev.capacity:
                cap_violations.append(
                    f"Trip {trip.departure.departure_id} at {ev.stop.name}: "
                    f"{ev.on_board_after}>{ev.capacity}"
                )
    report.checks.append(ConstraintCheck(
        constraint="C5: On-board passengers never exceed vehicle capacity",
        passed=len(cap_violations) == 0,
        detail=(
            f"{len(cap_violations)} violations: "
            f"{'; '.join(cap_violations[:3])}{'...' if len(cap_violations)>3 else ''}"
            if cap_violations else "No capacity violations"
        ),
    ))

    # C6: No negative on-board count
    neg_issues = [
        trip.departure.departure_id
        for trip in trips
        for ev in trip.stop_events
        if ev.on_board_after < 0
    ]
    report.checks.append(ConstraintCheck(
        constraint="C6: On-board count is never negative",
        passed=len(neg_issues) == 0,
        detail=f"Trips with negative count: {neg_issues}" if neg_issues else "OK",
    ))

    # C7: Arrival times non-decreasing within each trip
    order_issues = [
        trip.departure.departure_id
        for trip in trips
        if [ev.actual_arrival for ev in trip.stop_events] !=
           sorted(ev.actual_arrival for ev in trip.stop_events)
    ]
    report.checks.append(ConstraintCheck(
        constraint="C7: Arrival times non-decreasing within each trip",
        passed=len(order_issues) == 0,
        detail=f"Trips with ordering issues: {order_issues}" if order_issues else "OK",
    ))

    return report


def validate(plan: Plan, trips: List[SimulatedTrip] | None = None) -> ValidationReport:
    """Run all applicable checks and return a merged ValidationReport."""
    schedule_report = validate_plan_schedule(plan)
    if trips is not None:
        sim_report = validate_simulated_trips(plan, trips)
        merged = ValidationReport(plan_id=plan.plan_id)
        merged.checks = schedule_report.checks + sim_report.checks
        return merged
    return schedule_report
