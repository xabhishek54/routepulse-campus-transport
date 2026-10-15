"""
Discrete-event bus simulator for RoutePulse.

For each ScheduledDeparture in a Plan, this simulator:
  1. Advances stop by stop
  2. Draws travel-time noise (Gaussian around nominal) — sigma from config
  3. Samples passenger demand at each stop (Poisson, scaled by time-of-day)
  4. Applies optional disruption effects
  5. Records a StopEvent at each stop
  6. Returns a list of SimulatedTrip objects

All randomness is seeded per-trip for reproducibility.
"""
from __future__ import annotations
from typing import List, Optional, Dict

import numpy as np

from routepulse.config import (
    SEED, TRAVEL_NOISE_SIGMA, ALIGHTING_FRACTION,
)
from routepulse.models import (
    ScheduledDeparture, SimulatedTrip, StopEvent, Plan,
)
from routepulse.data_gen import passenger_demand


# ---------------------------------------------------------------------------
# Disruption descriptors
# ---------------------------------------------------------------------------
class Disruption:
    """Base class for disruption effects applied during simulation."""
    def travel_delay(self, departure_id: str, segment_idx: int, rng: np.random.Generator) -> float:
        return 0.0

    def demand_multiplier(self, stop_id: str, time_min: float) -> float:
        return 1.0

    def vehicle_available(self, departure_id: str) -> bool:
        return True


class DelayDisruption(Disruption):
    """Adds extra delay on specific route segments."""
    def __init__(self, affected_departure_ids: List[str], extra_delay_minutes: float):
        self.affected = set(affected_departure_ids)
        self.extra = extra_delay_minutes

    def travel_delay(self, departure_id: str, segment_idx: int, rng: np.random.Generator) -> float:
        if departure_id in self.affected:
            return self.extra * rng.uniform(0.5, 1.5)
        return 0.0


class DemandSpikeDisruption(Disruption):
    """Multiplies demand at a specific stop during a time window."""
    def __init__(self, stop_id: str, start_time: float, end_time: float, multiplier: float):
        self.stop_id = stop_id
        self.start = start_time
        self.end = end_time
        self.multiplier = multiplier

    def demand_multiplier(self, stop_id: str, time_min: float) -> float:
        if stop_id == self.stop_id and self.start <= time_min <= self.end:
            return self.multiplier
        return 1.0


class VehicleBreakdownDisruption(Disruption):
    """Simulates a vehicle breakdown — marks specified departures as unavailable."""
    def __init__(self, broken_departure_ids: List[str]):
        self.broken = set(broken_departure_ids)

    def vehicle_available(self, departure_id: str) -> bool:
        return departure_id not in self.broken


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------
def simulate_trip(
    departure: ScheduledDeparture,
    base_seed: int = SEED,
    disruptions: Optional[List[Disruption]] = None,
    travel_time_noise_sigma: float = TRAVEL_NOISE_SIGMA,
    alighting_fraction: float = ALIGHTING_FRACTION,
) -> Optional[SimulatedTrip]:
    """
    Simulate a single trip. Returns None if vehicle is unavailable (breakdown).

    travel_time_noise_sigma: std dev of Gaussian noise added to each segment (minutes).
    alighting_fraction: fraction of on-board passengers who alight at each stop.
    """
    disruptions = disruptions or []

    for d in disruptions:
        if not d.vehicle_available(departure.departure_id):
            return None

    trip_seed = hash((base_seed, departure.departure_id)) % (2**31)
    rng = np.random.default_rng(trip_seed)

    route = departure.route
    capacity = departure.vehicle.capacity

    on_board = 0
    current_time = departure.departure_time
    stop_events: List[StopEvent] = []

    for seg_idx, route_stop in enumerate(route.route_stops):
        stop = route_stop.stop
        scheduled_arr = departure.scheduled_arrival_at(stop.stop_id)

        if seg_idx > 0:
            seg_nominal = route_stop.segment_travel_time
            noise = rng.normal(0, travel_time_noise_sigma)
            extra = sum(d.travel_delay(departure.departure_id, seg_idx, rng) for d in disruptions)
            seg_actual = max(0.5, seg_nominal + noise + extra)
            current_time += seg_actual

        dis_mult = 1.0
        for d in disruptions:
            dis_mult *= d.demand_multiplier(stop.stop_id, current_time)
        demand = passenger_demand(stop, current_time, rng, dis_mult)

        alighted = 0
        if seg_idx > 0:
            alighted = int(round(on_board * alighting_fraction))
            on_board = max(0, on_board - alighted)

        space = capacity - on_board
        boarded = min(demand, space)
        on_board += boarded

        delay = current_time - scheduled_arr if scheduled_arr is not None else 0.0

        stop_events.append(StopEvent(
            stop=stop,
            scheduled_arrival=scheduled_arr or current_time,
            actual_arrival=current_time,
            demand_at_stop=demand,
            boarded=boarded,
            alighted=alighted,
            on_board_after=on_board,
            capacity=capacity,
            delay=delay,
        ))

    return SimulatedTrip(departure=departure, stop_events=stop_events, seed=base_seed)


def simulate_plan(
    plan: Plan,
    base_seed: int = SEED,
    disruptions: Optional[List[Disruption]] = None,
) -> List[SimulatedTrip]:
    """Simulate all departures in a plan. Cancelled trips (breakdown) are excluded."""
    trips = []
    for dep in plan.departures:
        trip = simulate_trip(dep, base_seed=base_seed, disruptions=disruptions)
        if trip is not None:
            trips.append(trip)
    return trips


def simulate_plan_multi_seed(
    plan: Plan,
    seeds: List[int],
    disruptions: Optional[List[Disruption]] = None,
) -> Dict[int, List[SimulatedTrip]]:
    """Run the plan under multiple seeds for robustness evaluation."""
    return {s: simulate_plan(plan, base_seed=s, disruptions=disruptions) for s in seeds}
