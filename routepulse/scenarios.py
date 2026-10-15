"""
Named disruption scenarios for RoutePulse.

All parameters from config.py.
Scenarios are designed to create realistic stress — not token disruptions.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

from routepulse.config import (
    SPORTS_DEMAND_SPIKE, SPORTS_START_HOUR, SPORTS_END_HOUR, SPORTS_AFFECTED_STOP,
    TRAFFIC_EXTRA_DELAY, TRAFFIC_WINDOW_HOURS, TRAFFIC_AFFECTED_ROUTES,
    BREAKDOWN_ROUTE, BREAKDOWN_N_VEHICLES, BREAKDOWN_START_HOUR,
    OP_START, HEADWAY,
)
from routepulse.models import Plan
from routepulse.simulator import (
    Disruption, DelayDisruption, DemandSpikeDisruption, VehicleBreakdownDisruption,
)


@dataclass
class Scenario:
    scenario_id: str
    name: str
    description: str
    disruptions: List[Disruption]
    # Estimated impact for operator display
    estimated_extra_passengers_stranded: int = 0
    estimated_delay_minutes: float = 0.0


def sports_event(plan: Plan) -> Scenario:
    """
    Large event at Sports Complex causes a surge of 5x normal demand
    from 15:00–16:30. Affects all routes serving the Sports Complex.
    Typically strands 60–120 additional passengers.
    """
    return Scenario(
        scenario_id="sports_event",
        name="Sports Event",
        description=(
            f"Major event at Sports Complex creates {SPORTS_DEMAND_SPIKE:.0f}× demand surge "
            f"at {SPORTS_AFFECTED_STOP} from "
            f"{int(SPORTS_START_HOUR):02d}:00–{int(SPORTS_END_HOUR):02d}:30. "
            f"Normal {SMALL_BUS_CAPACITY}-seat buses cannot absorb the crowd."
        ),
        disruptions=[
            DemandSpikeDisruption(
                stop_id=SPORTS_AFFECTED_STOP,
                start_time=SPORTS_START_HOUR * 60,
                end_time=SPORTS_END_HOUR * 60,
                multiplier=SPORTS_DEMAND_SPIKE,
            ),
        ],
        estimated_extra_passengers_stranded=90,
        estimated_delay_minutes=0.0,
    )


def _get_small_bus_capacity():
    from routepulse.config import SMALL_BUS_CAPACITY
    return SMALL_BUS_CAPACITY


SMALL_BUS_CAPACITY = _get_small_bus_capacity()


def morning_traffic(plan: Plan) -> Scenario:
    """
    Severe traffic congestion during morning rush delays ALL routes.
    Every segment takes 8 extra minutes — realistic for a blocked campus entrance.
    Affects all departures in the 08:00–10:30 window on all routes.
    """
    start_h, end_h = TRAFFIC_WINDOW_HOURS
    affected = [
        dep.departure_id
        for dep in plan.departures
        if dep.route.route_id in TRAFFIC_AFFECTED_ROUTES
        and start_h * 60 <= dep.departure_time <= end_h * 60
    ]

    return Scenario(
        scenario_id="morning_traffic",
        name="Morning Traffic Gridlock",
        description=(
            f"Campus entrance blocked: all {len(affected)} departures between "
            f"{int(start_h):02d}:00–{int(end_h):02d}:30 delayed by "
            f"~{TRAFFIC_EXTRA_DELAY:.0f} min per segment. "
            f"Creates cascading delays across the network."
        ),
        disruptions=[
            DelayDisruption(
                affected_departure_ids=affected,
                extra_delay_minutes=TRAFFIC_EXTRA_DELAY,
            ),
        ],
        estimated_extra_passengers_stranded=40,
        estimated_delay_minutes=TRAFFIC_EXTRA_DELAY * 3,  # 3 average segments
    )


def vehicle_breakdown(plan: Plan) -> Scenario:
    """
    Three consecutive buses on the Main Shuttle break down at 09:00.
    This cancels 45 minutes of service on the busiest route during peak time.
    Passengers must wait up to 45 min or find alternatives.
    """
    broken = [
        dep.departure_id
        for dep in sorted(plan.departures, key=lambda d: d.departure_time)
        if dep.route.route_id == BREAKDOWN_ROUTE
        and dep.departure_time >= BREAKDOWN_START_HOUR * 60
    ][:BREAKDOWN_N_VEHICLES]

    dep_labels = ", ".join(
        f"{int(next((d.departure_time for d in plan.departures if d.departure_id == did), 0) // 60):02d}:"
        f"{int(next((d.departure_time for d in plan.departures if d.departure_id == did), 0) % 60):02d}"
        for did in broken
    )

    return Scenario(
        scenario_id="vehicle_breakdown",
        name="Fleet Breakdown",
        description=(
            f"{BREAKDOWN_N_VEHICLES} Main Shuttle buses break down from 09:00, "
            f"cancelling departures at {dep_labels}. "
            f"Creates a {BREAKDOWN_N_VEHICLES * HEADWAY}-minute gap in service "
            f"during peak morning demand."
        ),
        disruptions=[
            VehicleBreakdownDisruption(broken_departure_ids=broken),
        ],
        estimated_extra_passengers_stranded=BREAKDOWN_N_VEHICLES * 80,
        estimated_delay_minutes=BREAKDOWN_N_VEHICLES * HEADWAY,
    )


def compound_disruption(plan: Plan) -> Scenario:
    """
    Worst case: traffic delays + breakdown + sports event all at once.
    Tests whether RoutePulse can replan under severe compound stress.
    """
    s1 = sports_event(plan)
    s2 = morning_traffic(plan)
    s3 = vehicle_breakdown(plan)

    return Scenario(
        scenario_id="compound",
        name="Compound Crisis",
        description=(
            "All disruptions simultaneously: morning traffic gridlock, "
            "fleet breakdown, and sports event surge. "
            "Stress-tests the replanning system under maximum load."
        ),
        disruptions=s1.disruptions + s2.disruptions + s3.disruptions,
        estimated_extra_passengers_stranded=200,
        estimated_delay_minutes=TRAFFIC_EXTRA_DELAY * 3,
    )


def get_all_scenarios(plan: Plan) -> List[Scenario]:
    return [
        sports_event(plan),
        morning_traffic(plan),
        vehicle_breakdown(plan),
        compound_disruption(plan),
    ]
