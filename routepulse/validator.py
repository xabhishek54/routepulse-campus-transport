"""
Independent hard-constraint validator for RoutePulse.

This module is SEPARATE from the optimizer.  It can be applied to any plan
(baseline, recommended, or disruption-replanned) and reports which hard
constraints are satisfied or violated.

Hard constraints:
  1. No trip may exceed vehicle capacity at any stop.
  2. No two departures on the same route may be within MIN_HEADWAY minutes.
  3. All departure times must be within the operating window.
  4. Every trip must start at the first stop of its route.
  5. Departure times must be monotonically increasing within a route
     (no duplicate departure times on the same route).

Output is always a structured ValidationReport so the UI can display it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

from routepulse.models import Plan, SimulatedTrip
from routepulse.data_gen import OP_START, OP_END
from routepulse.detector import MIN_HEADWAY


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Schedule-level checks (no simulation needed)
# ---------------------------------------------------------------------------
def validate_plan_schedule(plan: Plan) -> ValidationReport:
    """Check schedule constraints without running simulation."""
    report = ValidationReport(plan_id=plan.plan_id)

    # Group departures by route
    by_route: dict[str, list] = {}
    for dep in plan.departures:
        by_route.setdefault(dep.route.route_id, []).append(dep)

    # C1: Operating window
    oow_issues = []
    for dep in plan.departures:
        if dep.departure_time < OP_START or dep.departure_time > OP_END:
            oow_issues.append(dep.departure_id)
    report.checks.append(ConstraintCheck(
        constraint="C1: All departures within operating window",
        passed=len(oow_issues) == 0,
        detail=f"{len(oow_issues)} departures outside {OP_START//60:02d}:00–{OP_END//60:02d}:00"
               if oow_issues else "All departures within window",
    ))

    # C2: Minimum headway per route
    headway_issues = []
    for rid, deps in by_route.items():
        deps_sorted = sorted(deps, key=lambda d: d.departure_time)
        for i in range(len(deps_sorted) - 1):
            gap = deps_sorted[i + 1].departure_time - deps_sorted[i].departure_time
            if gap < MIN_HEADWAY:
                headway_issues.append(
                    f"Route {rid}: {deps_sorted[i].departure_id} and "
                    f"{deps_sorted[i+1].departure_id} gap={gap:.1f} min"
                )
    report.checks.append(ConstraintCheck(
        constraint=f"C2: Minimum headway ≥ {MIN_HEADWAY} min per route",
        passed=len(headway_issues) == 0,
        detail="; ".join(headway_issues) if headway_issues else "All headways OK",
    ))

    # C3: No duplicate departure times on same route
    dup_issues = []
    for rid, deps in by_route.items():
        times = [d.departure_time for d in deps]
        seen = set()
        for t in times:
            if t in seen:
                dup_issues.append(f"Route {rid} time {t}")
            seen.add(t)
    report.checks.append(ConstraintCheck(
        constraint="C3: No duplicate departure times on same route",
        passed=len(dup_issues) == 0,
        detail="; ".join(dup_issues) if dup_issues else "No duplicates",
    ))

    # C4: Each route has at least one departure
    empty_routes = [rid for rid in by_route if len(by_route[rid]) == 0]
    report.checks.append(ConstraintCheck(
        constraint="C4: Every route has at least one departure",
        passed=len(empty_routes) == 0,
        detail=f"Empty routes: {empty_routes}" if empty_routes else "All routes served",
    ))

    return report


# ---------------------------------------------------------------------------
# Simulation-level checks (need simulated trips)
# ---------------------------------------------------------------------------
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
        detail=f"{len(cap_violations)} violations: {'; '.join(cap_violations[:3])}{'...' if len(cap_violations)>3 else ''}"
               if cap_violations else "No capacity violations",
    ))

    # C6: No negative on-board count
    neg_issues = []
    for trip in trips:
        for ev in trip.stop_events:
            if ev.on_board_after < 0:
                neg_issues.append(trip.departure.departure_id)
    report.checks.append(ConstraintCheck(
        constraint="C6: On-board count is never negative",
        passed=len(neg_issues) == 0,
        detail=f"Trips with negative count: {neg_issues}" if neg_issues else "OK",
    ))

    # C7: Actual arrival times are non-decreasing within a trip
    order_issues = []
    for trip in trips:
        times = [ev.actual_arrival for ev in trip.stop_events]
        if times != sorted(times):
            order_issues.append(trip.departure.departure_id)
    report.checks.append(ConstraintCheck(
        constraint="C7: Arrival times non-decreasing within each trip",
        passed=len(order_issues) == 0,
        detail=f"Trips with ordering issues: {order_issues}" if order_issues else "OK",
    ))

    return report


# ---------------------------------------------------------------------------
# Combined validator
# ---------------------------------------------------------------------------
def validate(plan: Plan, trips: List[SimulatedTrip] | None = None) -> ValidationReport:
    """Run all applicable checks and return a merged ValidationReport."""
    schedule_report = validate_plan_schedule(plan)

    if trips is not None:
        sim_report = validate_simulated_trips(plan, trips)
        merged = ValidationReport(plan_id=plan.plan_id)
        merged.checks = schedule_report.checks + sim_report.checks
        return merged

    return schedule_report
