"""
Synthetic data generator for RoutePulse.

Generates a realistic fictional campus ("Westbrook University") with:
  - 8 stops
  - 3 routes
  - Demand model driven by class changeovers, lunch, and evening exodus
  - 2 vehicle types (small/large)
  - Fixed schedules per operating window, every HEADWAY min per route

All randomness is seeded for full reproducibility.
"""
from __future__ import annotations
import json
import math
import os
from typing import Dict, List, Tuple

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
# ---------------------------------------------------------------------------
def make_stops() -> Dict[str, Stop]:
    raw = [
        # stop_id, name, lat, lon, base_demand_rate (pax/hr peak)
        ("S1", "Main Gate",          51.5010, -0.1410, 30),
        ("S2", "Science Block",      51.5025, -0.1395, 45),
        ("S3", "Library Hub",        51.5035, -0.1375, 50),
        ("S4", "Student Union",      51.5020, -0.1360, 40),
        ("S5", "Residences North",   51.5045, -0.1400, 35),
        ("S6", "Sports Centre",      51.5015, -0.1340, 20),
        ("S7", "Engineering Block",  51.5040, -0.1355, 38),
        ("S8", "Medical School",     51.5030, -0.1415, 28),
    ]
    stops = {}
    for sid, name, lat, lon, demand in raw:
        stops[sid] = Stop(sid, name, lat, lon, float(demand))
    return stops


# ---------------------------------------------------------------------------
# Routes
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
        "R1": ("Campus Loop",      ["S1", "S2", "S3", "S4", "S6", "S1"]),
        "R2": ("North Connector",  ["S1", "S8", "S5", "S7", "S3"]),
        "R3": ("East Express",     ["S4", "S7", "S2", "S8", "S6"]),
    }
    routes = {}
    for rid, (name, stop_ids) in route_defs.items():
        rs = _make_route_stops(stops, stop_ids)
        routes[rid] = Route(rid, name, rs)
    return routes


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
def make_vehicles() -> Dict[str, Vehicle]:
    vehicles = {}
    for i in range(1, 5):
        vid = f"V{i:02d}"
        vehicles[vid] = Vehicle(vid, VEHICLE_TYPES["small"])
    for i in range(5, 8):
        vid = f"V{i:02d}"
        vehicles[vid] = Vehicle(vid, VEHICLE_TYPES["large"])
    return vehicles


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def make_schedule(
    routes: Dict[str, Route],
    vehicles: Dict[str, Vehicle],
    vehicle_assignment: Dict[str, str] | None = None,
) -> List[ScheduledDeparture]:
    """Generate departures every HEADWAY minutes for each route within operating hours."""
    default_assignment = {
        "R1": "V05",  # large — busiest loop
        "R2": "V01",  # small
        "R3": "V02",  # small
    }
    assignment = vehicle_assignment or default_assignment
    vehicle_map = dict(vehicles)
    departures = []
    dep_counter = 0

    for rid, route in routes.items():
        vid = assignment[rid]
        vehicle = vehicle_map[vid]
        t = OP_START
        while t <= OP_END - route.total_nominal_time:
            did = f"D{dep_counter:04d}"
            departures.append(ScheduledDeparture(did, route, float(t), vehicle))
            dep_counter += 1
            t += HEADWAY

    return departures


# ---------------------------------------------------------------------------
# Demand model
# ---------------------------------------------------------------------------

# Class-changeover peaks and their intensities — defined here as named data
DEMAND_PEAKS = [
    # (hour, strength) — strength is peak demand multiplier above base
    (9.0,  2.0),   # 09:00 morning rush
    (10.0, 1.5),   # 10:00 changeover
    (11.0, 1.5),   # 11:00 changeover
    (12.0, 2.5),   # 12:00 lunch
    (13.0, 2.0),   # 13:00 lunch/changeover
    (14.0, 1.5),   # 14:00 afternoon
    (15.0, 1.5),   # 15:00 changeover
    (16.0, 1.8),   # 16:00 late afternoon
    (17.0, 3.0),   # 17:00 evening exodus
]


def demand_multiplier(time_min: float) -> float:
    """Return a demand scaling factor (>1 = high demand) for a given time of day."""
    h = time_min / 60.0
    mult = BASE_OFF_PEAK_MULT
    for peak_h, strength in DEMAND_PEAKS:
        mult += strength * math.exp(-0.5 * ((h - peak_h) / PEAK_SIGMA_HOURS) ** 2)
    return max(0.1, mult)


def passenger_demand(
    stop: Stop,
    time_min: float,
    rng: np.random.Generator,
    disruption_multiplier: float = 1.0,
) -> int:
    """Sample passenger demand at a stop at a given time."""
    rate = stop.base_demand_rate * demand_multiplier(time_min) * disruption_multiplier
    return int(rng.poisson(rate * (HEADWAY / 60.0)))


# ---------------------------------------------------------------------------
# Seed data persistence
# ---------------------------------------------------------------------------
def _stop_to_dict(s: Stop) -> dict:
    return {
        "stop_id": s.stop_id, "name": s.name,
        "lat": s.lat, "lon": s.lon, "base_demand_rate": s.base_demand_rate,
    }


def _route_to_dict(r: Route) -> dict:
    return {
        "route_id": r.route_id,
        "name": r.name,
        "route_stops": [
            {
                "stop_id": rs.stop.stop_id,
                "segment_travel_time": rs.segment_travel_time,
                "cumulative_time": rs.cumulative_time,
            }
            for rs in r.route_stops
        ],
    }


def save_seed_data(stops, routes, vehicles, departures, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "stops.json"), "w") as f:
        json.dump([_stop_to_dict(s) for s in stops.values()], f, indent=2)

    with open(os.path.join(out_dir, "routes.json"), "w") as f:
        json.dump([_route_to_dict(r) for r in routes.values()], f, indent=2)

    with open(os.path.join(out_dir, "vehicles.json"), "w") as f:
        json.dump([
            {"vehicle_id": v.vehicle_id, "type_id": v.vehicle_type.type_id, "capacity": v.capacity}
            for v in vehicles.values()
        ], f, indent=2)

    dep_list = [
        {
            "departure_id": d.departure_id,
            "route_id": d.route.route_id,
            "departure_time": d.departure_time,
            "vehicle_id": d.vehicle.vehicle_id,
        }
        for d in departures
    ]
    with open(os.path.join(out_dir, "schedule.json"), "w") as f:
        json.dump(dep_list, f, indent=2)

    print(f"Seed data saved to {out_dir}")
    print(f"  {len(stops)} stops, {len(routes)} routes, {len(vehicles)} vehicles, {len(departures)} departures")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_campus(vehicle_assignment: Dict[str, str] | None = None):
    """Return (stops, routes, vehicles, departures) for Westbrook University."""
    stops = make_stops()
    routes = make_routes(stops)
    vehicles = make_vehicles()
    departures = make_schedule(routes, vehicles, vehicle_assignment)
    return stops, routes, vehicles, departures


def build_baseline_plan(
    stops=None, routes=None, vehicles=None, departures=None
) -> Plan:
    """Return the static baseline plan."""
    if departures is None:
        _, _, _, departures = build_campus()
    return Plan(
        plan_id="baseline_naive",
        name="Naive Baseline",
        description="Fixed static schedule, no adaptation. Vehicles never swapped.",
        departures=departures,
    )


def build_smarter_baseline_plan(stops=None, routes=None, vehicles=None) -> Plan:
    """
    Smarter baseline: swap to large bus on routes predicted to exceed
    SMARTER_BASELINE_THRESHOLD load at peak time (09:00).
    """
    if routes is None or vehicles is None:
        stops, routes, vehicles, _ = build_campus()

    peak_time = 9.0 * 60  # 09:00 in minutes
    peak_assignment = {}
    large_bus_ids = [vid for vid, v in vehicles.items()
                     if v.vehicle_type.type_id == "large"]
    small_bus_ids = [vid for vid, v in vehicles.items()
                     if v.vehicle_type.type_id == "small"]
    large_idx = 0
    small_idx = 0

    for rid, route in routes.items():
        rng_tmp = np.random.default_rng(SEED)
        est_load = sum(
            passenger_demand(rs.stop, peak_time, rng_tmp) for rs in route.route_stops
        )
        small_cap = VEHICLE_TYPES["small"].capacity
        if est_load / small_cap > SMARTER_BASELINE_THRESHOLD:
            peak_assignment[rid] = large_bus_ids[large_idx % len(large_bus_ids)]
            large_idx += 1
        else:
            peak_assignment[rid] = small_bus_ids[small_idx % len(small_bus_ids)]
            small_idx += 1

    _, _, _, departures = build_campus(vehicle_assignment=peak_assignment)
    return Plan(
        plan_id="baseline_smarter",
        name="Smarter Baseline",
        description=(
            f"Swaps to large bus on routes predicted to exceed "
            f"{SMARTER_BASELINE_THRESHOLD:.0%} peak load. No other changes."
        ),
        departures=departures,
        actions_applied=[],
    )


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
