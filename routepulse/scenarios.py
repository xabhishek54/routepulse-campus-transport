"""
Named disruption scenarios for RoutePulse demos.

Each scenario is a named, reproducible combination of disruptions and the
description to show the operator. The replay and replan pages use these
to demonstrate resilience and recovery.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

from routepulse.models import Plan
from routepulse.simulator import Disruption, DelayDisruption, DemandSpikeDisruption, VehicleBreakdownDisruption


@dataclass
class Scenario:
    scenario_id: str
    name: str
    description: str
    disruptions: List[Disruption]


def sports_event_spike(plan: Plan) -> Scenario:
    """
    Sports match at Sports Centre (S6) at 14:00–15:00.
    Demand at S6 triples; routes serving S6 experience extra load.
    """
    return Scenario(
        scenario_id="sports_event",
        name="Sports Event Surge",
        description=(
            "A match at the Sports Centre causes 3x demand spike at S6 between 14:00–15:00. "
            "Routes R1 and R3 serve this stop. Vehicles may become overcrowded."
        ),
        disruptions=[
            DemandSpikeDisruption(
                stop_id="S6",
                start_time=14 * 60,
                end_time=15 * 60,
                multiplier=3.0,
            )
        ],
    )


def morning_traffic_delay(plan: Plan) -> Scenario:
    """
    Heavy traffic at Main Gate during morning rush (08:00–10:00).
    First 8 departures on R1 and R2 experience extra travel delays.
    """
    # Identify departures in morning window on R1 and R2
    affected = [
        dep.departure_id
        for dep in plan.departures
        if dep.route.route_id in ("R1", "R2") and 8 * 60 <= dep.departure_time <= 10 * 60
    ][:8]

    return Scenario(
        scenario_id="morning_traffic",
        name="Morning Traffic Delay",
        description=(
            "Heavy congestion at Main Gate delays R1 and R2 departures in the 08:00–10:00 window. "
            "Each segment takes ~4 extra minutes."
        ),
        disruptions=[
            DelayDisruption(
                affected_departure_ids=affected,
                extra_delay_minutes=4.0,
            )
        ],
    )


def vehicle_breakdown(plan: Plan) -> Scenario:
    """
    One vehicle on R1 breaks down mid-morning (10:00 departure).
    """
    broken = [
        dep.departure_id
        for dep in plan.departures
        if dep.route.route_id == "R1" and 10 * 60 <= dep.departure_time <= 10 * 60 + 15
    ][:1]

    return Scenario(
        scenario_id="vehicle_breakdown",
        name="Vehicle Breakdown",
        description=(
            f"Vehicle on R1 (Campus Loop) at 10:00 breaks down. "
            f"Departure {broken[0] if broken else '?'} is cancelled. "
            "Passengers must wait for the next service."
        ),
        disruptions=[
            VehicleBreakdownDisruption(broken_departure_ids=broken),
        ],
    )


def compound_disruption(plan: Plan) -> Scenario:
    """
    Worst-case compound: traffic delays + demand spike + breakdown.
    """
    base_sports = sports_event_spike(plan)
    base_traffic = morning_traffic_delay(plan)
    base_break = vehicle_breakdown(plan)

    return Scenario(
        scenario_id="compound",
        name="Compound Disruption",
        description=(
            "All disruptions simultaneously: morning traffic, vehicle breakdown, and sports surge. "
            "Stress-tests the replanning capability."
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
