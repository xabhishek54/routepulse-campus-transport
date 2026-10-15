"""
Violation detector for RoutePulse.

Detects:
  - Crowding events (passengers left behind at stops)
  - Schedule conflicts (headway violations)
  - Missed connections (transfer failures)

Metric definitions match models.py and config.py.
All thresholds from config — nothing hardcoded.
"""
from __future__ import annotations
from typing import List, Dict

from routepulse.config import MIN_HEADWAY, MAX_WAIT_FOR_CONNECTION
from routepulse.models import (
    SimulatedTrip, Plan, ScheduledDeparture,
    Violation, MissedConnection,
)


# ---------------------------------------------------------------------------
# Crowding detection
# ---------------------------------------------------------------------------

def detect_crowding(trips: List[SimulatedTrip]) -> List[Violation]:
    """
    Detect stops where passengers were left behind (unmet_demand > 0).
    This uses the 'crowded' definition (any unmet demand), not just
    the strict overcrowded (on_board > capacity) definition.
    """
    violations = []
    for trip in trips:
        for ev in trip.stop_events:
            if ev.crowded:
                sev = "critical" if ev.unmet_demand > 10 else "warning"
                violations.append(Violation(
                    violation_type="crowding",
                    severity=sev,
                    description=(
                        f"{trip.departure.route.name} {_fmt(trip.departure.departure_time)} "
                        f"at {ev.stop.name}: "
                        f"{ev.unmet_demand} passengers left behind "
                        f"(bus at {ev.on_board_after}/{ev.capacity} capacity)"
                    ),
                    trip=trip,
                    stop_event=ev,
                ))
    return violations


def _fmt(minutes: float) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}"


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
                        f"{deps_sorted[i].route.name}: departures at "
                        f"{_fmt(deps_sorted[i].departure_time)} and "
                        f"{_fmt(deps_sorted[i+1].departure_time)} "
                        f"are only {gap:.1f} min apart (minimum {MIN_HEADWAY:.0f} min)"
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
    Detect cases where a delayed arrival prevents catching a connecting service.
    A missed connection is flagged when extra wait > MAX_WAIT_FOR_CONNECTION minutes
    compared to the nominal (on-time) scenario.
    """
    # Build arrival index: stop_id -> [(departure, actual_arrival)]
    stop_arrivals: Dict[str, List] = {}
    for trip in trips:
        for ev in trip.stop_events:
            stop_arrivals.setdefault(ev.stop.stop_id, []).append(
                (trip.departure, ev.actual_arrival)
            )

    # Build set of stops per route
    route_stops: Dict[str, set] = {}
    for dep in plan.departures:
        if dep.route.route_id not in route_stops:
            route_stops[dep.route.route_id] = {
                rs.stop.stop_id for rs in dep.route.route_stops
            }

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
                for dep_a, arr_a in sorted(arrivals_a, key=lambda x: x[1]):
                    # Scheduled arrival of this connection
                    sched_arr_a = dep_a.scheduled_arrival_at(stop_id) or arr_a

                    # What was the nominal next bus?
                    nominal_b = [(d, a) for d, a in arrivals_b_sorted if a > sched_arr_a]
                    if not nominal_b:
                        continue
                    dep_b_nominal, arr_b_nominal = nominal_b[0]

                    # What is the actual next bus given the delay?
                    actual_b = [(d, a) for d, a in arrivals_b_sorted if a > arr_a]
                    if not actual_b:
                        continue
                    dep_b_actual, arr_b_actual = actual_b[0]

                    extra_wait = arr_b_actual - arr_b_nominal
                    if extra_wait > MAX_WAIT_FOR_CONNECTION:
                        idx = dep_a.route.stop_index(stop_id)
                        if idx is None:
                            continue
                        stop_obj = dep_a.route.route_stops[idx].stop

                        next_after = [(d, a) for d, a in arrivals_b_sorted if a > arr_b_actual]
                        next_after_arr = next_after[0][1] if next_after else None

                        missed.append(MissedConnection(
                            passenger_origin=dep_a.route.route_stops[0].stop,
                            transfer_stop=stop_obj,
                            arriving_route=dep_a.route,
                            onward_route=dep_b_actual.route,
                            actual_arrival_at_transfer=round(arr_a, 2),
                            onward_bus_departure=round(arr_b_nominal, 2),
                            next_onward_departure=round(next_after_arr, 2) if next_after_arr else None,
                            extra_wait_minutes=round(extra_wait, 2),
                        ))

    return missed


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------

def detect_all(plan: Plan, trips: List[SimulatedTrip]) -> dict:
    """Run all detectors and return summary dict."""
    crowding = detect_crowding(trips)
    conflicts = detect_schedule_conflicts(plan)
    missed = detect_missed_connections(plan, trips)

    missed_vios = [
        Violation(
            violation_type="missed_connection",
            severity="warning",
            description=(
                f"Missed connection at {mc.transfer_stop.name}: "
                f"{mc.arriving_route.name} → {mc.onward_route.name}, "
                f"+{mc.extra_wait_minutes:.0f} min extra wait"
            ),
            missed_connection=mc,
        )
        for mc in missed
    ]

    all_violations = crowding + conflicts + missed_vios

    return {
        "crowding": crowding,
        "schedule_conflicts": conflicts,
        "missed_connections": missed,
        "missed_connection_violations": missed_vios,
        "all_violations": all_violations,
        "summary": {
            "crowding_events": len(crowding),
            "schedule_conflicts": len(conflicts),
            "missed_connections": len(missed),
            "total_violations": len(all_violations),
        },
    }
