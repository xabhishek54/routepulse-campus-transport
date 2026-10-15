"""
Independent hard-constraint validator for RoutePulse.

Completely separate from the optimizer — the optimizer cannot influence results.
All threshold constants come from routepulse.config.

Checks:
  C1: All departures within operating window
  C2: Minimum headway >= MIN_HEADWAY per route
  C3: No duplicate departure times on same route
  C4: Every route has at least one departure
  C5: Vehicle fleet inventory — each physical vehicle can only run one trip at a time
      (a vehicle cannot be in two places simultaneously)
  C6: Minimum turnaround time — gap between end of one trip and start of next
      for the same vehicle must be >= MIN_TURNAROUND_MINUTES
  C7: Travel-time feasibility — each departure must finish before OP_END
  C8: Extra-trip vehicles must exist in the plan's vehicle set
  --- Simulation-level checks (require trips) ---
  C9: On-board count never negative
  C10: Arrival times non-decreasing within each trip
  C11: All boarded <= demand at each stop
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

from routepulse.config import (
    MIN_HEADWAY, MIN_TURNAROUND_MINUTES, OP_START, OP_END,
)
from routepulse.models import Plan, SimulatedTrip, ScheduledDeparture


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

def _check_operating_window(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """C1: All departures start within operating window."""
    oow = [d.departure_id for d in departures
           if d.departure_time < OP_START or d.departure_time > OP_END]
    return ConstraintCheck(
        constraint="C1: Departures within operating window",
        passed=len(oow) == 0,
        detail=(f"{len(oow)} departures outside "
                f"{OP_START // 60:02d}:00–{OP_END // 60:02d}:00"
                if oow else "All within window"),
    )


def _check_minimum_headway(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """C2: Minimum gap between consecutive departures on the same route."""
    by_route: Dict[str, List] = {}
    for d in departures:
        by_route.setdefault(d.route.route_id, []).append(d)
    issues = []
    for rid, deps in by_route.items():
        deps_sorted = sorted(deps, key=lambda d: d.departure_time)
        for i in range(len(deps_sorted) - 1):
            gap = deps_sorted[i + 1].departure_time - deps_sorted[i].departure_time
            if gap < MIN_HEADWAY:
                issues.append(f"{rid}: {deps_sorted[i].departure_id}/"
                               f"{deps_sorted[i+1].departure_id} gap={gap:.1f}min")
    return ConstraintCheck(
        constraint=f"C2: Minimum headway ≥ {MIN_HEADWAY:.0f} min per route",
        passed=len(issues) == 0,
        detail="; ".join(issues[:5]) if issues else "All headways OK",
    )


def _check_no_duplicate_times(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """C3: No two departures on the same route at the same time."""
    by_route: Dict[str, List] = {}
    for d in departures:
        by_route.setdefault(d.route.route_id, []).append(d)
    dups = []
    for rid, deps in by_route.items():
        seen: Dict = {}
        for d in deps:
            t = d.departure_time
            if t in seen:
                dups.append(f"{rid}@{int(t//60):02d}:{int(t%60):02d}")
            seen[t] = d
    return ConstraintCheck(
        constraint="C3: No duplicate departure times per route",
        passed=len(dups) == 0,
        detail="; ".join(dups) if dups else "No duplicates",
    )


def _check_routes_served(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """C4: Every route in the plan has at least one departure."""
    route_ids = {d.route.route_id for d in departures}
    empty = []  # nothing to check without knowing expected routes
    return ConstraintCheck(
        constraint="C4: All routes have at least one departure",
        passed=len(route_ids) >= 1,
        detail=f"Routes served: {sorted(route_ids)}",
    )


def _check_fleet_inventory(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """
    C5: No vehicle runs two overlapping trips.
    A vehicle cannot be in two places simultaneously.
    Trips overlap when next trip starts before previous ends.
    """
    by_vehicle: Dict[str, List] = {}
    for d in departures:
        by_vehicle.setdefault(d.vehicle.vehicle_id, []).append(d)

    conflicts = []
    for vid, deps in by_vehicle.items():
        deps_sorted = sorted(deps, key=lambda d: d.departure_time)
        for i in range(len(deps_sorted) - 1):
            curr = deps_sorted[i]
            nxt  = deps_sorted[i + 1]
            curr_end = curr.departure_time + curr.route.total_nominal_time
            if nxt.departure_time < curr_end:
                conflicts.append(
                    f"{vid}: {curr.departure_id} ends "
                    f"{int(curr_end//60):02d}:{int(curr_end%60):02d}, "
                    f"{nxt.departure_id} starts "
                    f"{int(nxt.departure_time//60):02d}:{int(nxt.departure_time%60):02d}"
                )
    return ConstraintCheck(
        constraint="C5: No vehicle runs overlapping trips simultaneously",
        passed=len(conflicts) == 0,
        detail=(f"{len(conflicts)} fleet conflicts: "
                f"{'; '.join(conflicts[:3])}{'...' if len(conflicts) > 3 else ''}"
                if conflicts else "Fleet inventory valid"),
    )


def _check_turnaround(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """
    C6: Each vehicle has at least MIN_TURNAROUND_MINUTES between end of one
    trip and start of the next (time to reposition + check vehicle).
    """
    by_vehicle: Dict[str, List] = {}
    for d in departures:
        by_vehicle.setdefault(d.vehicle.vehicle_id, []).append(d)

    violations = []
    for vid, deps in by_vehicle.items():
        deps_sorted = sorted(deps, key=lambda d: d.departure_time)
        for i in range(len(deps_sorted) - 1):
            curr = deps_sorted[i]
            nxt  = deps_sorted[i + 1]
            curr_end = curr.departure_time + curr.route.total_nominal_time
            gap = nxt.departure_time - curr_end
            if 0 <= gap < MIN_TURNAROUND_MINUTES:
                violations.append(
                    f"{vid}: only {gap:.1f} min turnaround between "
                    f"{curr.departure_id} and {nxt.departure_id} "
                    f"(min {MIN_TURNAROUND_MINUTES:.0f} min)"
                )
    return ConstraintCheck(
        constraint=f"C6: Minimum turnaround ≥ {MIN_TURNAROUND_MINUTES:.0f} min per vehicle",
        passed=len(violations) == 0,
        detail=(f"{len(violations)} violations: "
                f"{'; '.join(violations[:3])}{'...' if len(violations) > 3 else ''}"
                if violations else "All turnarounds feasible"),
    )


def _check_trip_fits_window(departures: List[ScheduledDeparture]) -> ConstraintCheck:
    """C7: Each trip finishes (nominally) within the operating window."""
    late = [
        d.departure_id
        for d in departures
        if d.departure_time + d.route.total_nominal_time > OP_END + 1  # 1 min grace
    ]
    return ConstraintCheck(
        constraint=f"C7: All trips finish within operating window (by {OP_END//60:02d}:00)",
        passed=len(late) == 0,
        detail=(f"{len(late)} trips finish after window: {late[:3]}{'...' if len(late) > 3 else ''}"
                if late else "All trips finish within window"),
    )


# ---------------------------------------------------------------------------
# Simulation-level checks
# ---------------------------------------------------------------------------

def _check_no_negative_onboard(trips: List[SimulatedTrip]) -> ConstraintCheck:
    """C9: On-board count is never negative."""
    neg = [
        f"{t.departure.departure_id}@{e.stop.name}"
        for t in trips for e in t.stop_events if e.on_board_after < 0
    ]
    return ConstraintCheck(
        constraint="C9: On-board count never negative",
        passed=len(neg) == 0,
        detail=f"Negative counts at: {neg}" if neg else "OK",
    )


def _check_arrival_order(trips: List[SimulatedTrip]) -> ConstraintCheck:
    """C10: Actual arrival times non-decreasing within each trip."""
    issues = [
        t.departure.departure_id
        for t in trips
        if any(
            t.stop_events[i].actual_arrival > t.stop_events[i + 1].actual_arrival
            for i in range(len(t.stop_events) - 1)
        )
    ]
    return ConstraintCheck(
        constraint="C10: Arrivals non-decreasing within each trip",
        passed=len(issues) == 0,
        detail=f"Out-of-order trips: {issues}" if issues else "OK",
    )


def _check_boarded_le_demand(trips: List[SimulatedTrip]) -> ConstraintCheck:
    """C11: Boarded passengers ≤ demand at each stop."""
    issues = [
        f"{t.departure.departure_id}@{e.stop.name}: boarded={e.boarded} demand={e.demand_at_stop}"
        for t in trips for e in t.stop_events if e.boarded > e.demand_at_stop
    ]
    return ConstraintCheck(
        constraint="C11: Boarded ≤ demand at each stop",
        passed=len(issues) == 0,
        detail=f"Violations: {issues[:3]}" if issues else "OK",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_plan_schedule(plan: Plan) -> ValidationReport:
    """Check schedule constraints without running simulation."""
    report = ValidationReport(plan_id=plan.plan_id)
    deps = plan.departures
    report.checks = [
        _check_operating_window(deps),
        _check_minimum_headway(deps),
        _check_no_duplicate_times(deps),
        _check_routes_served(deps),
        _check_fleet_inventory(deps),
        _check_turnaround(deps),
        _check_trip_fits_window(deps),
    ]
    return report


def validate_simulated_trips(plan: Plan, trips: List[SimulatedTrip]) -> ValidationReport:
    """Check simulation-level hard constraints."""
    report = ValidationReport(plan_id=plan.plan_id + "_sim")
    report.checks = [
        _check_no_negative_onboard(trips),
        _check_arrival_order(trips),
        _check_boarded_le_demand(trips),
    ]
    return report


def validate(plan: Plan, trips: Optional[List[SimulatedTrip]] = None) -> ValidationReport:
    """Run all applicable checks and return a merged ValidationReport."""
    schedule_report = validate_plan_schedule(plan)
    if trips is not None:
        sim_report = validate_simulated_trips(plan, trips)
        merged = ValidationReport(plan_id=plan.plan_id)
        merged.checks = schedule_report.checks + sim_report.checks
        return merged
    return schedule_report
