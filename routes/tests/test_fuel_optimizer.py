"""
Unit tests for the Fuel Optimization Algorithm.
Tests all mathematical calculations, vehicle range boundaries, and greedy decision paths.
"""
import pytest
from routes.services.fuel_optimizer import FuelOptimizer
from routes.services.station_service import FuelStation
from routes.exceptions import NoFeasibleFuelPlanException


def create_station(station_id, name, distance_miles, price, lat=40.0, lon=-80.0):
    return FuelStation(
        opis_id=str(station_id),
        name=name,
        address=f"Highway Exit {station_id}",
        city="Test City",
        state="OH",
        rack_id="100",
        price=price,
        latitude=lat,
        longitude=lon,
        distance_along_route=float(distance_miles),
        corridor_offset_miles=1.0,
    )


class TestFuelOptimizer:
    def setup_method(self):
        self.optimizer = FuelOptimizer(max_range_miles=500.0, mpg=10.0)

    def test_short_100_mile_route_zero_stops(self):
        stations = [
            create_station(1, "Station A", 50.0, 3.50),
        ]
        plan = self.optimizer.optimize(total_distance=100.0, candidate_stations=stations)
        assert len(plan.stops) == 0
        assert plan.total_gallons_consumed == 10.0
        assert plan.total_gallons_purchased == 0.0
        assert plan.total_fuel_cost == 0.0

    def test_exact_500_mile_route_zero_stops(self):
        stations = [
            create_station(1, "Station Mid", 250.0, 3.20),
        ]
        plan = self.optimizer.optimize(total_distance=500.0, candidate_stations=stations)
        assert len(plan.stops) == 0
        assert plan.total_gallons_consumed == 50.0
        assert plan.total_gallons_purchased == 0.0
        assert plan.total_fuel_cost == 0.0

    def test_501_mile_route_requires_one_stop(self):
        stations = [
            create_station(1, "Station Mid", 300.0, 3.00),
        ]
        plan = self.optimizer.optimize(total_distance=501.0, candidate_stations=stations)
        assert len(plan.stops) == 1
        assert plan.stops[0].station.opis_id == "1"
        assert plan.total_gallons_consumed == 50.1
        # Traveled 300 miles on initial tank (leaving 20 gal).
        # Need to travel 201 miles to destination (needs 20.1 gal).
        # 20.1 - 20 = 0.1 gal needed!
        assert round(plan.total_gallons_purchased, 2) == 0.1
        assert round(plan.total_fuel_cost, 2) == round(0.1 * 3.00, 2)

    def test_cheapest_unreachable_forces_expensive_stop(self):
        # Station A (300 mi, $3.80) is reachable from start.
        # Station B (650 mi, $2.50) is cheaper but unreachable on starting 500-mi tank!
        # Destination is at 800 miles.
        stations = [
            create_station(1, "Station A Expensive", 300.0, 3.80),
            create_station(2, "Station B Cheap", 650.0, 2.50),
        ]
        plan = self.optimizer.optimize(total_distance=800.0, candidate_stations=stations)

        # Vehicle must stop at Station A to reach Station B or destination
        assert len(plan.stops) >= 1
        assert plan.stops[0].station.name == "Station A Expensive"

    def test_cheaper_station_selected_when_reachable(self):
        # Station A is at 250 miles with price $3.80
        # Station B is at 450 miles with price $3.10 (cheaper and reachable within 500-mi tank!)
        # Destination is at 800 miles.
        stations = [
            create_station(1, "Station A", 250.0, 3.80),
            create_station(2, "Station B", 450.0, 3.10),
        ]
        plan = self.optimizer.optimize(total_distance=800.0, candidate_stations=stations)

        # Optimizer should bypass expensive Station A and refuel at cheaper Station B!
        assert len(plan.stops) == 1
        assert plan.stops[0].station.name == "Station B"
        assert plan.stops[0].station.price == 3.10
        # Arrive at 450 mi with 5 gal left. Need to reach 800 mi (350 mi = 35 gal).
        # Buy 35 - 5 = 30 gallons at $3.10 = $93.00
        assert round(plan.stops[0].gallons_purchased, 2) == 30.0
        assert round(plan.total_fuel_cost, 2) == 93.00

    def test_multiple_fuel_stops_for_long_route(self):
        # 1400-mile journey with stations along the way
        stations = [
            create_station(1, "Stop 1", 400.0, 3.20),
            create_station(2, "Stop 2", 850.0, 3.30),
            create_station(3, "Stop 3", 1200.0, 3.15),
        ]
        plan = self.optimizer.optimize(total_distance=1400.0, candidate_stations=stations)
        assert len(plan.stops) >= 2
        # Verify no consecutive legs exceed 500 miles
        legs = [plan.stops[0].station.distance_along_route]
        for i in range(1, len(plan.stops)):
            legs.append(plan.stops[i].station.distance_along_route - plan.stops[i-1].station.distance_along_route)
        legs.append(1400.0 - plan.stops[-1].station.distance_along_route)
        for leg in legs:
            assert leg <= 500.0

        # Mathematical verification: total cost equals sum of each stop cost
        calculated_cost = sum(s.cost for s in plan.stops)
        assert round(calculated_cost, 2) == round(plan.total_fuel_cost, 2)

    def test_destination_reachable_without_another_stop(self):
        # At mile 400 with full tank purchased, destination is at 750 miles (350 miles away <= 500)
        stations = [
            create_station(1, "Stop 1", 400.0, 3.50),
            create_station(2, "Stop 2", 600.0, 3.90),
        ]
        plan = self.optimizer.optimize(total_distance=750.0, candidate_stations=stations)
        assert len(plan.stops) == 1
        assert plan.stops[0].station.name == "Stop 1"

    def test_no_feasible_route_first_leg_gap(self):
        # First station is at 550 miles (> 500 miles from start). Vehicle cannot reach it!
        stations = [
            create_station(1, "Far Station", 550.0, 3.00),
        ]
        with pytest.raises(NoFeasibleFuelPlanException):
            self.optimizer.optimize(total_distance=800.0, candidate_stations=stations)

    def test_no_feasible_route_intermediate_gap(self):
        # Station 1 is at 300 miles. Station 2 is at 850 miles (gap of 550 miles > 500 miles).
        stations = [
            create_station(1, "Station 1", 300.0, 3.00),
            create_station(2, "Station 2", 850.0, 3.00),
        ]
        with pytest.raises(NoFeasibleFuelPlanException):
            self.optimizer.optimize(total_distance=1100.0, candidate_stations=stations)

    def test_no_stations_available_on_long_route(self):
        with pytest.raises(NoFeasibleFuelPlanException):
            self.optimizer.optimize(total_distance=800.0, candidate_stations=[])

    def test_case_5_expensive_station_required_because_only_reachable(self):
        """
        Assessment Case 5: Expensive station is required because it is the only reachable station.
        Must select it to prevent stranding.
        """
        # Distance = 900 miles.
        # Station A: 400 miles, price $4.80 (expensive, but only bridge to destination or cheaper station)
        # Station B: 850 miles, price $2.10 (cheap, but 850 miles from start > 500 max range)
        stations = [
            create_station(1, "Expensive Bridge", 400.0, 4.80),
            create_station(2, "Cheap Ahead", 850.0, 2.10),
        ]
        plan = self.optimizer.optimize(total_distance=900.0, candidate_stations=stations)
        assert len(plan.stops) >= 1
        assert plan.stops[0].station.name == "Expensive Bridge"

    def test_case_6_cheaper_station_reachable_ahead_prevents_excess_purchase(self):
        """
        Assessment Case 6: A cheaper station is reachable ahead.
        The optimizer should avoid unnecessarily buying excessive fuel at the current expensive station.
        """
        # Start at 0 mi.
        # Stop 1 at 350 mi, price $4.00.
        # Stop 2 at 650 mi (300 mi from Stop 1 <= 500 mi range), price $2.50.
        # Destination at 1000 mi (350 mi from Stop 2 <= 500 mi range).
        stations = [
            create_station(1, "Expensive Station", 350.0, 4.00),
            create_station(2, "Cheap Station", 650.0, 2.50),
        ]
        plan = self.optimizer.optimize(total_distance=1000.0, candidate_stations=stations)
        assert len(plan.stops) == 2
        stop1, stop2 = plan.stops[0], plan.stops[1]
        assert stop1.station.name == "Expensive Station"
        assert stop2.station.name == "Cheap Station"

        # Arrive at Stop 1 (350 mi) with 15 gal left from starting full tank (50 - 35).
        # Distance from Stop 1 to Stop 2 is 300 mi (needs 30 gal).
        # Optimizer must only purchase 30 - 15 = 15 gallons at $4.00 (NOT fill full 35 gallons!).
        assert round(stop1.gallons_purchased, 2) == 15.0
        assert round(stop1.cost, 2) == 60.0  # 15 * 4.00

        # At Stop 2 (cheap station), it fills up to reach destination (350 mi = 35 gal).
        # Total purchased should equal exactly 100 gal consumed - 50 gal starting = 50 gal purchased!
        assert round(plan.total_gallons_consumed, 2) == 100.0
        assert round(plan.total_gallons_purchased, 2) == 50.0

    def test_starting_fuel_not_charged(self):
        """
        Verify initial 50 gallons in starting tank are never charged in total_fuel_cost.
        """
        stations = [
            create_station(1, "Mid Stop", 400.0, 3.00),
        ]
        # Route 600 miles -> 60 gallons consumed. 50 gallons from starting tank -> 10 purchased.
        plan = self.optimizer.optimize(total_distance=600.0, candidate_stations=stations)
        assert round(plan.total_gallons_consumed, 2) == 60.0
        assert round(plan.total_gallons_purchased, 2) == 10.0
        assert round(plan.total_fuel_cost, 2) == 30.00  # 10 gal * $3.00

    def test_intermediate_leg_exactly_500_miles(self):
        """
        Verify that an intermediate leg of exactly 500.0 miles between stations is feasible.
        """
        stations = [
            create_station(1, "Stop 1", 400.0, 3.10),
            create_station(2, "Stop 2", 900.0, 3.20),  # Exactly 500 miles from Stop 1
        ]
        plan = self.optimizer.optimize(total_distance=1100.0, candidate_stations=stations)
        assert len(plan.stops) == 2
        assert plan.stops[0].station.name == "Stop 1"
        assert plan.stops[1].station.name == "Stop 2"

    def test_intermediate_leg_exceeding_500_miles_fails(self):
        """
        Verify that an intermediate leg of 500.1 miles between stations raises NoFeasibleFuelPlan.
        """
        stations = [
            create_station(1, "Stop 1", 400.0, 3.10),
            create_station(2, "Stop 2", 900.1, 3.20),  # 500.1 miles from Stop 1 (> 500 max range)
        ]
        with pytest.raises(NoFeasibleFuelPlanException):
            self.optimizer.optimize(total_distance=1100.0, candidate_stations=stations)
