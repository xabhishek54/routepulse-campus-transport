"""
Tests for domain models.
"""
import pytest
from routepulse.models import Stop, VehicleType, Vehicle, RouteStop, Route, ScheduledDeparture


def test_stop_distance():
    a = Stop("A", "A", 51.500, -0.140, 10)
    b = Stop("B", "B", 51.501, -0.140, 10)
    d = a.distance_km(b)
    assert 0.05 < d < 0.20, f"Expected ~0.11 km, got {d}"


def test_route_stop_index():
    s1 = Stop("S1", "A", 51.50, -0.14, 10)
    s2 = Stop("S2", "B", 51.51, -0.14, 10)
    rs1 = RouteStop(s1, 0.0, 0.0)
    rs2 = RouteStop(s2, 3.0, 3.0)
    route = Route("R1", "Test Route", [rs1, rs2])
    assert route.stop_index("S1") == 0
    assert route.stop_index("S2") == 1
    assert route.stop_index("S99") is None


def test_scheduled_arrival():
    s1 = Stop("S1", "A", 51.50, -0.14, 10)
    s2 = Stop("S2", "B", 51.51, -0.14, 10)
    rs1 = RouteStop(s1, 0.0, 0.0)
    rs2 = RouteStop(s2, 5.0, 5.0)
    route = Route("R1", "Test Route", [rs1, rs2])
    vt = VehicleType("small", "Mini", 25)
    v = Vehicle("V01", vt)
    dep = ScheduledDeparture("D0001", route, 480.0, v)
    assert dep.scheduled_arrival_at("S1") == 480.0
    assert dep.scheduled_arrival_at("S2") == 485.0
    assert dep.scheduled_arrival_at("S99") is None


def test_vehicle_capacity():
    vt = VehicleType("large", "Bus", 40)
    v = Vehicle("V05", vt)
    assert v.capacity == 40
