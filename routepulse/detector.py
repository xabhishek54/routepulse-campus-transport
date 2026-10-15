"""
Violation and issue detector for RoutePulse.

All thresholds come from routepulse.config — nothing is hardcoded here.
"""
from __future__ import annotations
from typing import List, Dict

from routepulse.config import MIN_HEADWAY, MAX_WAIT_FOR_CONNECTION
from routepulse.models import (
    SimulatedTrip, Plan, ScheduledDeparture,
    Violation, MissedConnection,
)


# ---------------------------------------------------------------------------
# Overcrowding detection
# ---------------------------------------------------------------------------
def detect_overcrowding(trips: List[SimulatedTrip]) -> List[Violation]:
    violations = []
    for trip in trips:
        for ev in trip.stop_events:
            if ev.overcrowded:
                overage = ev.on_board_after - ev.capacity
                sev = "critical" if overage > 5 else "warning"
                violations.append(Violation(
                    violation_type="overcrowding",
                    severity=sev,
                    description=(
                        f"Trip {trip.departure.departure_id} at {ev.stop.name}: "
                        f"{ev.on_board_after}/{ev.capacity} passengers "
                        f"({overage} over capacity)"
                    ),
                    trip=trip,
                    stop_event=ev,
                ))
    return violations


# ---------------------------------------------------------------------------
# Schedule conflict detection
# ---------------------------------------------------------------------------
def detect_schedule_conflicts(plan: Plan) -> List[Violation]:
    """Detect same-route departures with headway below MIN_HEADWAY."""
    by_route: Dict[str, List[ScheduledDeparture]] = {}
    for dep in plan.departures:
        by_route.setdefault(dep.route.route_id, []).append(dep)

    violations = []
    for rid, deps in by_route.items():
        deps_sorted = sorted(deps, key=lambda d: d.departure_time)
        for i in range(len(deps_sorted) - 1):
            gap = deps_sorted[i + 1].departure_time - deps_sorted[i].departure_time
            if gap < MIN_HEADWAY:
                violations.append(Violation(
                    violation_type="schedule_conflict",
                    severity="critical",
                    description=(
                        f"Route {rid}: departures {deps_sorted[i].departure_id} and "
                        f"{deps_sorted[i+1].departure_id} only {gap:.1f} min apart "
                        f"(min headway {MIN_HEADWAY} min)"
                    ),
                ))
    return violations


# ---------------------------------------------------------------------------
# Missed connection detection
# ---------------------------------------------------------------------------
def detect_missed_connections(
    plan: Plan,
    trips: List[SimulatedTrip],
) -> List[MissedConnection]:
    """
    Find cases where a delay causes a passenger to miss their onward connection.
    A missed connection is detected when extra wait exceeds MAX_WAIT_FOR_CONNECTION.
    """
    stop_arrivals: Dict[str, List[tuple]] = {}
    for trip in trips:
        for ev in trip.stop_events:
            stop_arrivals.setdefault(ev.stop.stop_id, []).append(
                (trip.departure, ev.actual_arrival)
            )

    route_stops: Dict[str, set] = {}
    for dep in plan.departures:
        rid = dep.route.route_id
        if rid not in route_stops:
            route_stops[rid] = {rs.stop.stop_id for rs in dep.route.route_stops}

    route_ids = list(route_stops.keys())
    missed: List[MissedConnection] = []

    for i, rid_a in enumerate(route_ids):
        for rid_b in route_ids[i + 1:]:
            shared = route_stops[rid_a] & route_stops[rid_b]
            for stop_id in shared:
                arrivals_a = [
                    (dep, arr) for dep, arr in stop_arrivals.get(stop_id, [])
                    if dep.route.route_id == rid_a
                ]
                arrivals_b = [
                    (dep, arr) for dep, arr in stop_arrivals.get(stop_id, [])
                    if dep.route.route_id == rid_b
                ]
                if not arrivals_a or not arrivals_b:
                    continue

                arrivals_b_sorted = sorted(arrivals_b, key=lambda x: x[1])
                arrivals_a_sorted = sorted(arrivals_a, key=lambda x: x[1])

                for dep_a, arr_a in arrivals_a_sorted:
                    onward = [(dep_b, arr_b) for dep_b, arr_b in arrivals_b_sorted if arr_b > arr_a]
                    if not onward:
                        continue
                    dep_b_next, arr_b_next = onward[0]

                    sched_arr_a = dep_a.scheduled_arrival_at(stop_id) or arr_a
                    nominal_onward = [
                        (dep_b, arr_b) for dep_b, arr_b in arrivals_b_sorted if arr_b > sched_arr_a
                    ]
                    if not nominal_onward:
                        continue
                    dep_b_nominal, arr_b_nominal = nominal_onward[0]

                    extra_wait = arr_b_next - arr_b_nominal
                    if extra_wait > MAX_WAIT_FOR_CONNECTION:
                        idx = dep_a.route.stop_index(stop_id)
                        if idx is None:
                            continue
                        stop_obj = dep_a.route.route_stops[idx].stop
                        next_next = [(d, a) for d, a in arrivals_b_sorted if a > arr_b_next]
                        next_next_arr = next_next[0][1] if next_next else None

                        missed.append(MissedConnection(
                            passenger_origin=dep_a.route.route_stops[0].stop,
                            transfer_stop=stop_obj,
                            arriving_route=dep_a.route,
                            onward_route=dep_b_next.route,
                            actual_arrival_at_transfer=round(arr_a, 2),
                            onward_bus_departure=round(arr_b_nominal, 2),
                            next_onward_departure=round(next_next_arr, 2) if next_next_arr else None,
                            extra_wait_minutes=round(extra_wait, 2),
                        ))

    return missed


# ---------------------------------------------------------------------------
# Combined detection
# ---------------------------------------------------------------------------
def detect_all(plan: Plan, trips: List[SimulatedTrip]) -> dict:
    """Run all detectors and return a summary dict."""
    overcrowding = detect_overcrowding(trips)
    schedule_conflicts = detect_schedule_conflicts(plan)
    missed = detect_missed_connections(plan, trips)

    missed_violations = [
        Violation(
            violation_type="missed_connection",
            severity="warning",
            description=(
                f"Missed connection at {mc.transfer_stop.name}: "
                f"{mc.arriving_route.name} → {mc.onward_route.name}, "
                f"+{mc.extra_wait_minutes:.1f} min extra wait"
            ),
            missed_connection=mc,
        )
        for mc in missed
    ]

    all_violations = overcrowding + schedule_conflicts + missed_violations

    return {
        "overcrowding": overcrowding,
        "schedule_conflicts": schedule_conflicts,
        "missed_connections": missed,
        "missed_connection_violations": missed_violations,
        "all_violations": all_violations,
        "summary": {
            "overcrowding_events": len(overcrowding),
            "schedule_conflicts": len(schedule_conflicts),
            "missed_connections": len(missed),
            "total_violations": len(all_violations),
        },
    }
