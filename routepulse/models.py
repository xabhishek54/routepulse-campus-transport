"""
RoutePulse core domain models.

All times are represented as minutes since midnight (integer or float).
Coordinates are (lat, lon) tuples representing campus locations.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import math


@dataclass
class Stop:
    """A physical bus stop on campus."""
    stop_id: str
    name: str
    lat: float
    lon: float
    # Expected peak-hour boarding demand (passengers/hour) — used for demand scaling
    base_demand_rate: float = 5.0

    def distance_km(self, other: "Stop") -> float:
        """Haversine distance in km."""
        R = 6371.0
        lat1, lon1 = math.radians(self.lat), math.radians(self.lon)
        lat2, lon2 = math.radians(other.lat), math.radians(other.lon)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return R * 2 * math.asin(math.sqrt(a))


@dataclass
class VehicleType:
    """A type of vehicle with a fixed passenger capacity."""
    type_id: str
    name: str
    capacity: int  # max passengers


@dataclass
class Vehicle:
    """A specific vehicle instance."""
    vehicle_id: str
    vehicle_type: VehicleType

    @property
    def capacity(self) -> int:
        return self.vehicle_type.capacity


@dataclass
class RouteStop:
    """A stop within a route, with cumulative nominal travel time from route origin."""
    stop: Stop
    # Nominal travel time (minutes) from the previous stop; 0 for first stop
    segment_travel_time: float
    # Cumulative nominal time from route start (minutes)
    cumulative_time: float = 0.0


@dataclass
class Route:
    """A campus bus route."""
    route_id: str
    name: str
    route_stops: List[RouteStop]  # ordered list of stops

    @property
    def stops(self) -> List[Stop]:
        return [rs.stop for rs in self.route_stops]

    @property
    def total_nominal_time(self) -> float:
        """Total nominal run time in minutes."""
        return self.route_stops[-1].cumulative_time if self.route_stops else 0.0

    def stop_index(self, stop_id: str) -> Optional[int]:
        for i, rs in enumerate(self.route_stops):
            if rs.stop.stop_id == stop_id:
                return i
        return None


@dataclass
class ScheduledDeparture:
    """A single scheduled departure of a route."""
    departure_id: str
    route: Route
    # Departure time from the first stop (minutes since midnight)
    departure_time: float
    vehicle: Vehicle

    def scheduled_arrival_at(self, stop_id: str) -> Optional[float]:
        """Return the scheduled arrival time at a given stop, or None if not on this route."""
        idx = self.route.stop_index(stop_id)
        if idx is None:
            return None
        return self.departure_time + self.route.route_stops[idx].cumulative_time


@dataclass
class StopEvent:
    """Records what happened at a stop during a simulated trip."""
    stop: Stop
    scheduled_arrival: float        # minutes since midnight
    actual_arrival: float           # minutes since midnight
    demand_at_stop: int             # passengers waiting when bus arrived
    boarded: int                    # passengers who boarded
    alighted: int                   # passengers who alighted
    on_board_after: int             # passengers on bus after this stop
    capacity: int                   # vehicle capacity
    delay: float                    # actual_arrival - scheduled_arrival (minutes)

    @property
    def overcrowded(self) -> bool:
        return self.on_board_after > self.capacity

    @property
    def unmet_demand(self) -> int:
        return max(0, self.demand_at_stop - self.boarded)


@dataclass
class SimulatedTrip:
    """Full simulation result for one scheduled departure."""
    departure: ScheduledDeparture
    stop_events: List[StopEvent]
    seed: int

    @property
    def has_overcrowding(self) -> bool:
        return any(e.overcrowded for e in self.stop_events)

    @property
    def total_unmet_demand(self) -> int:
        return sum(e.unmet_demand for e in self.stop_events)

    @property
    def max_delay(self) -> float:
        return max((e.delay for e in self.stop_events), default=0.0)

    @property
    def final_delay(self) -> float:
        return self.stop_events[-1].delay if self.stop_events else 0.0


@dataclass
class ETAEstimate:
    """Arrival-window estimate for a vehicle approaching a stop."""
    stop: Stop
    scheduled_arrival: float          # minutes since midnight
    estimated_arrival: float          # Kalman-filtered point estimate
    uncertainty_minutes: float        # half-width of 90% confidence interval
    current_delay: float              # observed delay so far (minutes)
    confidence_pct: float = 90.0      # CI coverage (%)

    @property
    def lower_bound(self) -> float:
        return self.estimated_arrival - self.uncertainty_minutes

    @property
    def upper_bound(self) -> float:
        return self.estimated_arrival + self.uncertainty_minutes


@dataclass
class MissedConnection:
    """A detected missed connection event."""
    passenger_origin: Stop
    transfer_stop: Stop
    arriving_route: Route
    onward_route: Route
    actual_arrival_at_transfer: float    # when passenger arrives
    onward_bus_departure: float          # when the onward bus left
    next_onward_departure: Optional[float]  # next available, if any
    extra_wait_minutes: float            # additional wait beyond nominal


@dataclass
class Violation:
    """A detected constraint violation."""
    violation_type: str   # "overcrowding" | "schedule_conflict" | "missed_connection" | "capacity"
    severity: str         # "warning" | "critical"
    description: str
    trip: Optional[SimulatedTrip] = None
    stop_event: Optional[StopEvent] = None
    missed_connection: Optional[MissedConnection] = None


@dataclass
class RecommendationAction:
    """A single recommended change."""
    action_type: str   # "vehicle_swap" | "extra_trip" | "departure_nudge" | "frequency_increase"
    description: str
    departure: Optional[ScheduledDeparture] = None
    new_vehicle: Optional[Vehicle] = None
    time_shift_minutes: float = 0.0
    cost_label: str = ""
    benefit_label: str = ""


@dataclass
class Plan:
    """A transport plan — either baseline or a recommended modification."""
    plan_id: str
    name: str
    description: str
    departures: List[ScheduledDeparture]
    actions_applied: List[RecommendationAction] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Metrics for a simulated plan."""
    plan: Plan
    eta_mae: float                  # minutes
    eta_calibration: float          # fraction (0–1) of estimates where actual in CI
    overcrowding_events: int        # count of stop-events where on_board > capacity
    total_unmet_demand: int         # passengers who couldn't board
    missed_connections: int         # count of missed-connection events
    average_wait_minutes: float     # mean passenger wait
    fleet_utilisation: float        # mean load/capacity across all stops
    constraint_violations: int      # independent validator count
    seeds_used: List[int] = field(default_factory=list)
