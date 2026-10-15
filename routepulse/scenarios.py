"""
Named disruption scenarios for RoutePulse demos.
All parameters come from routepulse.config — nothing hardcoded here.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

from routepulse.config import (
    SPORTS_DEMAND_SPIKE, SPORTS_START_HOUR, SPORTS_END_HOUR,
    TRAFFIC_EXTRA_DELAY, TRAFFIC_WINDOW_HOURS,
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


def sports_event_spike(plan: Plan) -> Scenario:
    """Sports match at Sports Centre (S6) causes demand spike."""
    return Scenario(
        scenario_id="sports_event",
        name="Sports Event Surge",
        description=(
            f"A match at the Sports Centre causes {SPORTS_DEMAND_SPIKE:.0f}x demand "
            f"spike at S6 between {SPORTS_START_HOUR:.0f}:00–{SPORTS_END_HOUR:.0f}:00. "
            "Routes R1 and R3 serve this stop. Vehicles may become overcrowded."
        ),
        disruptions=[
            DemandSpikeDisruption(
                stop_id="S6",
                start_time=SPORTS_START_HOUR * 60,
                end_time=SPORTS_END_HOUR * 60,
                multiplier=SPORTS_DEMAND_SPIKE,
            )
        ],
    )


def morning_traffic_delay(plan: Plan) -> Scenario:
    """Heavy traffic at Main Gate during morning rush."""
    start_h, end_h = TRAFFIC_WINDOW_HOURS
    affected = [
        dep.departure_id
        for dep in plan.departures
        if dep.route.route_id in ("R1", "R2")
        and start_h * 60 <= dep.departure_time <= end_h * 60
    ][:8]

    return Scenario(
        scenario_id="morning_traffic",
        name="Morning Traffic Delay",
        description=(
            f"Heavy congestion at Main Gate delays R1 and R2 departures "
            f"in the {start_h:.0f}:00–{end_h:.0f}:00 window. "
            f"Each segment takes ~{TRAFFIC_EXTRA_DELAY:.0f} extra minutes."
        ),
        disruptions=[
            DelayDisruption(
                affected_departure_ids=affected,
                extra_delay_minutes=TRAFFIC_EXTRA_DELAY,
            )
        ],
    )


def vehicle_breakdown(plan: Plan) -> Scenario:
    """One vehicle on R1 breaks down at the 10:00 departure."""
    broken = [
        dep.departure_id
        for dep in plan.departures
        if dep.route.route_id == "R1"
        and 10 * 60 <= dep.departure_time <= 10 * 60 + 15
    ][:1]

    dep_label = broken[0] if broken else "?"
    return Scenario(
        scenario_id="vehicle_breakdown",
        name="Vehicle Breakdown",
        description=(
            f"Vehicle on R1 (Campus Loop) at 10:00 breaks down. "
            f"Departure {dep_label} is cancelled. "
            "Passengers must wait for the next service."
        ),
        disruptions=[
            VehicleBreakdownDisruption(broken_departure_ids=broken),
        ],
    )


def compound_disruption(plan: Plan) -> Scenario:
    """Worst-case compound: traffic delays + demand spike + breakdown."""
    base_sports  = sports_event_spike(plan)
    base_traffic = morning_traffic_delay(plan)
    base_break   = vehicle_breakdown(plan)

    return Scenario(
        scenario_id="compound",
        name="Compound Disruption",
        description=(
            "All disruptions simultaneously: morning traffic, vehicle breakdown, "
            "and sports event surge. Stress-tests the replanning capability."
        ),
        disruptions=(
            base_sports.disruptions
            + base_traffic.disruptions
            + base_break.disruptions
        ),
    )


def get_all_scenarios(plan: Plan) -> List[Scenario]:
    return [
        sports_event_spike(plan),
        morning_traffic_delay(plan),
        vehicle_breakdown(plan),
        compound_disruption(plan),
    ]
