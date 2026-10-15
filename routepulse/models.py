"""
RoutePulse core domain models.

All times are represented as minutes since midnight (integer or float).
Coordinates are (lat, lon) tuples representing campus locations.

Metric definitions (canonical — referenced throughout the codebase):
  overcrowding_event: stop-event where on_board_after >= capacity (at or above)
  crowding_event:     stop-event where unmet_demand > 0 (passengers left behind)
  unmet_demand:       count of passengers who arrived and could not board
  delay:              actual_arrival - scheduled_arrival at a stop (minutes, + = late)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
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
        """Return the index of the FIRST occurrence of this stop on the route."""
        for i, rs in enumerate(self.route_stops):
            if rs.stop.stop_id == stop_id:
                return i
        return None

    def stop_indices(self, stop_id: str) -> List[int]:
        """Return ALL indices where this stop appears (needed for loop routes)."""
        return [i for i, rs in enumerate(self.route_stops) if rs.stop.stop_id == stop_id]


@dataclass
class ScheduledDeparture:
    """A single scheduled departure of a route."""
    departure_id: str
    route: Route
    # Departure time from the first stop (minutes since midnight)
    departure_time: float
    vehicle: Vehicle

    def scheduled_arrival_at(self, stop_id: str, occurrence: int = 0) -> Optional[float]:
        """
        Return the scheduled arrival time at a given stop.

        occurrence=0 means first occurrence (departure stop for loops).
        occurrence=-1 means last occurrence (arrival stop for loop terminals).
        Pass occurrence=-1 when computing the return leg of a loop route.
        """
        indices = self.route.stop_indices(stop_id)
        if not indices:
            return None
        if occurrence == -1:
            idx = indices[-1]
        else:
            idx = indices[min(occurrence, len(indices) - 1)]
        return self.departure_time + self.route.route_stops[idx].cumulative_time

    def scheduled_arrival_at_position(self, position: int) -> Optional[float]:
        """Return scheduled arrival at the nth stop (0-indexed). Unambiguous even for loops."""
        if 0 <= position < len(self.route.route_stops):
            return self.departure_time + self.route.route_stops[position].cumulative_time
        return None


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
        """True when bus is at or over capacity (on_board >= capacity).
        See metric definitions in models.py docstring."""
        return self.on_board_after >= self.capacity

    @property
    def unmet_demand(self) -> int:
        """Passengers who arrived but could not board."""
        return max(0, self.demand_at_stop - self.boarded)

    @property
    def crowded(self) -> bool:
        """True when any passengers were left behind at this stop."""
        return self.unmet_demand > 0


@dataclass
class SimulatedTrip:
    """Full simulation result for one scheduled departure."""
    departure: ScheduledDeparture
    stop_events: List[StopEvent]
    seed: int

    @property
    def has_overcrowding(self) -> bool:
        """Any stop at or above capacity."""
        return any(e.overcrowded for e in self.stop_events)

    @property
    def has_crowding(self) -> bool:
        """Any passengers were left behind."""
        return any(e.crowded for e in self.stop_events)

    @property
    def total_unmet_demand(self) -> int:
        """Total passengers left behind across all stops."""
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
    violation_type: str   # "overcrowding" | "schedule_conflict" | "missed_connection" | "fleet_conflict" | "turnaround"
    severity: str         # "warning" | "critical"
    description: str
    trip: Optional[SimulatedTrip] = None
    stop_event: Optional[StopEvent] = None
    missed_connection: Optional[MissedConnection] = None


@dataclass
class RecommendationAction:
    """A single recommended change to the schedule."""
    action_type: str   # "vehicle_upgrade" | "extra_trip" | "departure_shift"
    description: str
    departure: Optional[ScheduledDeparture] = None
    new_vehicle: Optional[Vehicle] = None
    time_shift_minutes: float = 0.0
    # Computed from simulation data — no fabricated numbers
    passengers_accommodated: int = 0    # how many previously-unmet passengers this action serves
    cost_vehicle_minutes: float = 0.0   # extra vehicle-minutes this action requires


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
    """Metrics for a simulated plan across one or more seeds."""
    plan: Plan
    # ETA quality (separate from plan-outcome metrics)
    eta_mae: float                  # minutes — lower is better
    eta_calibration: float          # fraction (0–1); target = CI_PCT/100
    # Plan outcome metrics
    overcrowding_events: int        # stop-events where on_board >= capacity
    crowding_events: int            # stop-events where any passenger left behind
    total_unmet_demand: int         # total passengers who couldn't board
    passengers_served: int = 0      # total passengers who boarded
    service_rate: float = 0.0       # boarded / total_demand
    missed_connections: int = 0     # count of missed-connection events
    average_wait_minutes: float = 0.0  # proxy: HEADWAY/2 + mean positive delay
    fleet_utilisation: float = 0.0  # mean on_board/capacity across all stop-events
    # Constraint compliance
    constraint_violations: int = 0  # independent validator count
    seeds_used: List[int] = field(default_factory=list)
    # Spread (filled by multi-seed eval)
    unmet_demand_std: float = 0.0
    overcrowding_std: float = 0.0
    service_rate_std: float = 0.0
