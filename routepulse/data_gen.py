"""
Synthetic data generator for RoutePulse.

Generates Westbrook University — a fictional campus with:
  - 10 stops across a realistic campus layout
  - 4 routes covering different quadrants
  - Heavy demand at peak times (class start/end, lunch, evening)
  - 2 vehicle types: minibus (30 seats) and bus (60 seats)
  - All routes use small minibuses in the naive baseline, creating genuine congestion

Design philosophy:
  - Naive baseline: all small buses → real overcrowding at peak
  - Smarter baseline: upgrades the busiest ROUTES (not trips) to large buses — blunt instrument
  - RoutePulse: upgrades specific TRIPS and adds targeted extras — surgical

All randomness is seeded for full reproducibility.
"""
from __future__ import annotations
import json
import math
import os
from typing import Dict, List, Optional

import numpy as np

from routepulse.config import (
    SEED, OP_START, OP_END, HEADWAY,
    SMALL_BUS_CAPACITY, LARGE_BUS_CAPACITY, CAMPUS_BUS_SPEED_KMH,
    DWELL_TIME_MINUTES, BASE_OFF_PEAK_MULT, PEAK_SIGMA_HOURS,
    SMARTER_BASELINE_THRESHOLD,
)
from routepulse.models import (
    Stop, VehicleType, Vehicle, RouteStop, Route,
    ScheduledDeparture, Plan,
)

RNG = np.random.default_rng(SEED)

# ---------------------------------------------------------------------------
# Vehicle types — defined from config, not hardcoded here
# ---------------------------------------------------------------------------
VEHICLE_TYPES = {
    "small": VehicleType("small", f"Minibus ({SMALL_BUS_CAPACITY})", SMALL_BUS_CAPACITY),
    "large": VehicleType("large", f"Bus ({LARGE_BUS_CAPACITY})", LARGE_BUS_CAPACITY),
}


# ---------------------------------------------------------------------------
# Campus stops — Westbrook University
# Coordinates: fictional campus, ~1 km across
# base_demand_rate: passengers/hour at peak (9:00 rush)
# ---------------------------------------------------------------------------
def make_stops() -> Dict[str, Stop]:
    raw = [
        # id, name, lat, lon, peak demand (pax/hr)
        # Note: coordinates spread ~1.5km to be realistic on map
        ("S01", "Main Entrance",      51.5000, -0.1500, 80),   # high: everyone enters here
        ("S02", "Central Square",     51.5015, -0.1470, 70),   # hub, connections
        ("S03", "Science Faculty",    51.5030, -0.1445, 90),   # large lecture theatres
        ("S04", "Engineering Block",  51.5025, -0.1415, 75),   # morning peak very high
        ("S05", "Library & IT",       51.5010, -0.1440, 55),   # steady all day
        ("S06", "Student Union",      51.5000, -0.1460, 65),   # lunch rush
        ("S07", "Halls North",        51.5040, -0.1480, 85),   # morning departure rush
        ("S08", "Sports Complex",     51.5045, -0.1445, 30),   # event-dependent
        ("S09", "Medical School",     51.5035, -0.1415, 60),   # steady, some peak
        ("S10", "Business School",    51.5005, -0.1420, 70),   # 09:00 and 14:00 peaks
    ]
    stops = {}
    for sid, name, lat, lon, demand in raw:
        stops[sid] = Stop(sid, name, lat, lon, float(demand))
    return stops


# ---------------------------------------------------------------------------
# Routes — 4 routes serving different campus areas
# ---------------------------------------------------------------------------
def _make_route_stops(stops: Dict[str, Stop], ordered_ids: List[str]) -> List[RouteStop]:
    route_stops = []
    cumulative = 0.0
    prev_stop = None
    for sid in ordered_ids:
        s = stops[sid]
        if prev_stop is None:
            seg_time = 0.0
        else:
            dist = prev_stop.distance_km(s)
            seg_time = (dist / CAMPUS_BUS_SPEED_KMH) * 60 + DWELL_TIME_MINUTES
        cumulative += seg_time
        route_stops.append(RouteStop(s, seg_time, round(cumulative, 2)))
        prev_stop = s
    return route_stops


def make_routes(stops: Dict[str, Stop]) -> Dict[str, Route]:
    route_defs = {
        # R1: Main shuttle — busiest, serves halls + all main academic stops
        "R1": ("Main Shuttle",        ["S07", "S02", "S03", "S04", "S09", "S02", "S06", "S01"]),
        # R2: North loop — serves halls + science + engineering
        "R2": ("North Loop",          ["S01", "S02", "S07", "S08", "S03", "S04"]),
        # R3: South express — fast route between entrance and business + library
        "R3": ("South Express",       ["S01", "S06", "S05", "S10", "S04", "S09"]),
        # R4: Cross-campus — connects east and west sides
        "R4": ("Cross-Campus Link",   ["S03", "S09", "S10", "S05", "S06", "S02"]),
    }
    routes = {}
    for rid, (name, stop_ids) in route_defs.items():
        rs = _make_route_stops(stops, stop_ids)
        routes[rid] = Route(rid, name, rs)
    return routes


# ---------------------------------------------------------------------------
# Fleet — larger pool so each vehicle runs a feasible schedule
# ---------------------------------------------------------------------------
def make_vehicles() -> Dict[str, Vehicle]:
    """
    Fleet: 8 small buses, 4 large buses.
    The naive baseline assigns one small bus to each route.
    Multiple physical vehicles share the same type; the schedule assigns
    a named vehicle to each departure, cycling through the fleet.
    """
    vehicles = {}
    for i in range(1, 9):   # S01–S08 small buses
        vid = f"S{i:02d}"
        vehicles[vid] = Vehicle(vid, VEHICLE_TYPES["small"])
    for i in range(1, 5):   # L01–L04 large buses
        vid = f"L{i:02d}"
        vehicles[vid] = Vehicle(vid, VEHICLE_TYPES["large"])
    return vehicles


# ---------------------------------------------------------------------------
# Schedule — assigns vehicles to departures
# For realism, each route has a *pool* of vehicles that rotate through the day.
# The schedule is feasible: each vehicle has enough turnaround time.
# ---------------------------------------------------------------------------
def make_schedule(
    routes: Dict[str, Route],
    vehicles: Dict[str, Vehicle],
    route_vehicle_type: Dict[str, str] | None = None,
) -> List[ScheduledDeparture]:
    """
    Generate departures every HEADWAY minutes for each route, with
    a physically feasible vehicle assignment.

    Each route gets its own ISOLATED pool of virtual vehicles, sized so
    no vehicle is ever double-booked.  The minimum pool size per route is:
        ceil((route_time + MIN_TURNAROUND_MINUTES) / HEADWAY)

    Virtual IDs are route-scoped (e.g. "R1-S01") so vehicles from
    different routes never appear in the same constraint check.

    route_vehicle_type: maps route_id -> 'small' | 'large'.
    Defaults to naive baseline (all small).
    """
    import math as _math
    from routepulse.config import MIN_TURNAROUND_MINUTES

    if route_vehicle_type is None:
        route_vehicle_type = {rid: "small" for rid in routes}

    # Lookup templates from the provided fleet
    type_templates = {v.vehicle_type.type_id: v.vehicle_type for v in vehicles.values()}

    departures: List[ScheduledDeparture] = []
    dep_counter = 0

    for rid, route in routes.items():
        vtype = route_vehicle_type.get(rid, "small")
        route_time = route.total_nominal_time

        # Minimum vehicles to cover the headway without double-booking
        n_needed = _math.ceil((route_time + MIN_TURNAROUND_MINUTES) / HEADWAY)
        n_needed = max(n_needed, 1)

        vtype_obj = type_templates.get(vtype) or type_templates.get("small")
        prefix = "L" if vtype == "large" else "S"

        # Route-local pool with unique IDs
        route_pool = [
            Vehicle(f"{rid}-{prefix}{i+1:02d}", vtype_obj)
            for i in range(n_needed)
        ]
        free_at: Dict[str, float] = {v.vehicle_id: float(OP_START) for v in route_pool}

        t = float(OP_START)
        while t + route_time <= OP_END + 1:
            did = f"D{dep_counter:04d}"

            # Pick the free vehicle with the earliest availability
            eligible = [v for v in route_pool if free_at[v.vehicle_id] <= t]
            if eligible:
                best = min(eligible, key=lambda v: free_at[v.vehicle_id])
            else:
                best = min(route_pool, key=lambda v: free_at[v.vehicle_id])

            departures.append(ScheduledDeparture(did, route, t, best))
            free_at[best.vehicle_id] = t + route_time + MIN_TURNAROUND_MINUTES
            dep_counter += 1
            t += HEADWAY

    return departures


# ---------------------------------------------------------------------------
# Demand model — realistic campus with sharp peaks
# ---------------------------------------------------------------------------

DEMAND_PEAKS = [
    # (centre_hour, multiplier) — sharp peaks at class-changeover times
    # Stronger peaks than before: campus actually gets congested
    (8.5,  3.5),   # 08:30: halls emptying, first lectures
    (9.0,  4.5),   # 09:00: main morning rush (strongest peak)
    (10.0, 2.5),   # 10:00: changeover
    (11.0, 2.0),   # 11:00: changeover
    (12.0, 3.5),   # 12:00: lunch rush
    (13.0, 3.0),   # 13:00: post-lunch
    (14.0, 2.0),   # 14:00: afternoon changeover
    (15.0, 2.0),   # 15:00: changeover
    (16.0, 2.5),   # 16:00: late afternoon
    (17.0, 4.0),   # 17:00: evening exodus (second strongest peak)
    (18.0, 2.5),   # 18:00: evening classes starting
]


def demand_multiplier(time_min: float) -> float:
    """Return a demand scaling factor for a given time (minutes since midnight)."""
    h = time_min / 60.0
    mult = BASE_OFF_PEAK_MULT
    for peak_h, strength in DEMAND_PEAKS:
        mult += strength * math.exp(-0.5 * ((h - peak_h) / PEAK_SIGMA_HOURS) ** 2)
    return max(0.05, mult)


def passenger_demand(
    stop: Stop,
    time_min: float,
    rng: np.random.Generator,
    disruption_multiplier: float = 1.0,
) -> int:
    """Sample passenger demand at a stop at a given time."""
    rate = stop.base_demand_rate * demand_multiplier(time_min) * disruption_multiplier
    # Rate is pax/hr; scale by headway (how long until next bus)
    return int(rng.poisson(max(0.1, rate * (HEADWAY / 60.0))))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_campus(route_vehicle_type: Dict[str, str] | None = None):
    """Return (stops, routes, vehicles, departures) for Westbrook University."""
    stops = make_stops()
    routes = make_routes(stops)
    vehicles = make_vehicles()
    departures = make_schedule(routes, vehicles, route_vehicle_type)
    return stops, routes, vehicles, departures


def build_naive_baseline(
    stops=None, routes=None, vehicles=None, departures=None
) -> Plan:
    """
    Naive baseline: all routes use small minibuses all day.
    This creates genuine peak-hour overcrowding — there IS something to optimise.
    """
    if departures is None:
        _, _, _, departures = build_campus()
    return Plan(
        plan_id="baseline_naive",
        name="Naive Baseline",
        description=(
            "All routes run with 30-seat minibuses throughout the day. "
            "No demand-aware adjustments. Peak trips become overcrowded."
        ),
        departures=departures,
    )


# Keep alias for backward compatibility
def build_baseline_plan(stops=None, routes=None, vehicles=None, departures=None) -> Plan:
    return build_naive_baseline(stops=stops, routes=routes, vehicles=vehicles, departures=departures)


def build_smarter_baseline_plan(
    stops=None, routes=None, vehicles=None, departures=None
) -> Plan:
    """
    Smarter baseline: use large buses on routes where DAILY average load
    is predicted to exceed threshold. This is a blunt, static rule —
    it upgrades entire routes all day, not just congested trips.

    This is a fair but beatable baseline: it pays the cost of large buses
    all day even during off-peak when they're not needed, and it can't
    add extra trips or nudge departure times.
    """
    if routes is None or vehicles is None:
        stops, routes, vehicles, _ = build_campus()

    rng_tmp = np.random.default_rng(SEED)
    peak_time = 9.0 * 60  # 09:00

    route_vehicle_type = {}
    for rid, route in routes.items():
        # Estimate how full the route gets at peak with a small bus
        est_load_per_trip = sum(
            passenger_demand(rs.stop, peak_time, rng_tmp)
            for rs in route.route_stops
        )
        # Multiple stops board passengers; compare to capacity
        if est_load_per_trip / SMALL_BUS_CAPACITY > SMARTER_BASELINE_THRESHOLD:
            route_vehicle_type[rid] = "large"
        else:
            route_vehicle_type[rid] = "small"

    _, _, _, departures = build_campus(route_vehicle_type=route_vehicle_type)

    upgraded_routes = [rid for rid, vt in route_vehicle_type.items() if vt == "large"]
    return Plan(
        plan_id="baseline_smarter",
        name="Rule-Based Baseline",
        description=(
            f"Upgrades routes {', '.join(upgraded_routes)} to 60-seat buses all day "
            f"based on predicted peak load > {SMARTER_BASELINE_THRESHOLD:.0%} of small-bus capacity. "
            "Blunt: pays for large buses during off-peak too, cannot add trips or shift times."
        ),
        departures=departures,
        actions_applied=[],
    )


# ---------------------------------------------------------------------------
# Seed data persistence (for debugging / auditing)
# ---------------------------------------------------------------------------
def _stop_to_dict(s: Stop) -> dict:
    return {"stop_id": s.stop_id, "name": s.name, "lat": s.lat,
            "lon": s.lon, "base_demand_rate": s.base_demand_rate}


def _route_to_dict(r: Route) -> dict:
    return {
        "route_id": r.route_id, "name": r.name,
        "route_stops": [{"stop_id": rs.stop.stop_id,
                          "segment_travel_time": rs.segment_travel_time,
                          "cumulative_time": rs.cumulative_time}
                         for rs in r.route_stops],
    }


def save_seed_data(stops, routes, vehicles, departures, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "stops.json"), "w") as f:
        json.dump([_stop_to_dict(s) for s in stops.values()], f, indent=2)
    with open(os.path.join(out_dir, "routes.json"), "w") as f:
        json.dump([_route_to_dict(r) for r in routes.values()], f, indent=2)
    with open(os.path.join(out_dir, "vehicles.json"), "w") as f:
        json.dump([{"vehicle_id": v.vehicle_id, "type_id": v.vehicle_type.type_id,
                    "capacity": v.capacity} for v in vehicles.values()], f, indent=2)
    dep_list = [{"departure_id": d.departure_id, "route_id": d.route.route_id,
                 "departure_time": d.departure_time, "vehicle_id": d.vehicle.vehicle_id}
                for d in departures]
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(dep_list, f, indent=2)
    print(f"Saved {len(stops)} stops, {len(routes)} routes, {len(vehicles)} vehicles, {len(departures)} departures to {out_dir}")


if __name__ == "__main__":
    import sys
    stops, routes, vehicles, departures = build_campus()
    out = "data/seed"
    if len(sys.argv) > 1:
        out = sys.argv[1]
    save_seed_data(stops, routes, vehicles, departures, out)
    print("\nRoutes:")
    for r in routes.values():
        times = [f"{rs.stop.name}({rs.cumulative_time:.1f}m)" for rs in r.route_stops]
        print(f"  {r.route_id} {r.name}: {' -> '.join(times)}")
    print(f"\nTotal departures: {len(departures)}")
