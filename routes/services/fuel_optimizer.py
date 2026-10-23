"""
Fuel Optimization Algorithm.
Solves the vehicle refueling problem:
- 500 miles max vehicle range.
- 10 MPG fuel efficiency (50 gallons tank capacity).
- Starts with a full tank (50 gallons).
- Minimizes total money spent on fuel while strictly respecting vehicle range.
- Supports multi-stop journeys across the United States.
"""
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from routes.exceptions import NoFeasibleFuelPlanException
from routes.services.station_service import FuelStation

logger = logging.getLogger(__name__)


@dataclass
class OptimizedFuelStop:
    """Represents a recommended fuel stop with purchase details."""
    station: FuelStation
    gallons_purchased: float
    cost: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'station_id': str(self.station.opis_id),
            'station_name': self.station.name,
            'address': self.station.address,
            'city': self.station.city,
            'state': self.station.state,
            'price_per_gallon': round(self.station.price, 3),
            'distance_from_start_miles': round(self.station.distance_along_route, 1),
            'gallons_purchased': round(self.gallons_purchased, 2),
            'cost': round(self.cost, 2),
            'latitude': round(self.station.latitude, 5),
            'longitude': round(self.station.longitude, 5),
        }


@dataclass
class FuelPlan:
    """Complete fuel plan result."""
    total_distance_miles: float
    total_gallons_consumed: float
    total_gallons_purchased: float
    total_fuel_cost: float
    stops: List[OptimizedFuelStop]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'fuel_stops': [s.to_dict() for s in self.stops],
            'fuel_summary': {
                'total_gallons_consumed': round(self.total_gallons_consumed, 2),
                'total_gallons_purchased': round(self.total_gallons_purchased, 2),
                'total_fuel_cost': round(self.total_fuel_cost, 2),
            }
        }


class FuelOptimizer:
    """
    Deterministic fuel optimizer implementing the optimal greedy refueling strategy.
    """

    def __init__(self, max_range_miles: float = 500.0, mpg: float = 10.0):
        self.max_range = float(max_range_miles)
        self.mpg = float(mpg)
        self.tank_capacity = self.max_range / self.mpg  # 50.0 gallons

    def optimize(self, total_distance: float, candidate_stations: List[FuelStation]) -> FuelPlan:
        """
        Determines the optimal sequence of fuel stops and purchase quantities.
        """
        total_distance = round(total_distance, 2)
        total_gallons_consumed = round(total_distance / self.mpg, 2)

        # 1. Trivial case: Destination is directly reachable on initial full tank
        if total_distance <= self.max_range:
            logger.info("Total distance %.1f miles is within initial tank range (%.1f miles). No fuel stops required.",
                        total_distance, self.max_range)
            return FuelPlan(
                total_distance_miles=total_distance,
                total_gallons_consumed=total_gallons_consumed,
                total_gallons_purchased=0.0,
                total_fuel_cost=0.0,
                stops=[]
            )

        # 2. Filter stations to valid forward progress along the route
        valid_stations = [
            s for s in candidate_stations
            if 0.0 < s.distance_along_route < total_distance
        ]
        valid_stations.sort(key=lambda s: s.distance_along_route)

        # 3. Check reachability via reverse dynamic reachability graph
        # Node 0: Start (dist=0)
        # Nodes 1..N: Stations
        # Node N+1: Destination (dist=total_distance)
        all_nodes = [{'dist': 0.0, 'station': None, 'price': float('inf')}]
        for s in valid_stations:
            all_nodes.append({'dist': s.distance_along_route, 'station': s, 'price': s.price})
        all_nodes.append({'dist': total_distance, 'station': None, 'price': 0.0})

        n = len(all_nodes)
        can_reach_dest = [False] * n
        can_reach_dest[-1] = True  # Destination can reach itself

        for i in range(n - 2, -1, -1):
            for j in range(i + 1, n):
                if all_nodes[j]['dist'] - all_nodes[i]['dist'] <= self.max_range:
                    if can_reach_dest[j]:
                        can_reach_dest[i] = True
                        break
                else:
                    break

        if not can_reach_dest[0]:
            logger.warning("No feasible fuel plan: vehicle cannot reach destination within %.1f-mile range legs.", self.max_range)
            raise NoFeasibleFuelPlanException(
                message=f"No fuel station combination can cover the route within the {int(self.max_range)}-mile vehicle range."
            )

        # Filter nodes to only those that can reach the destination
        # 4. Greedy Refueling Simulation
        stops: List[OptimizedFuelStop] = []
        curr_idx = 0
        curr_dist = 0.0
        curr_fuel = self.tank_capacity  # Starts with full tank (50 gallons)

        # Safety counter to prevent infinite loop under any degenerate condition
        max_iterations = len(all_nodes) * 2
        iteration = 0

        while curr_dist < total_distance and iteration < max_iterations:
            iteration += 1

            # Can we reach destination with current fuel?
            if total_distance - curr_dist <= (curr_fuel * self.mpg) + 1e-6:
                break

            # Handle departure from START
            if curr_idx == 0:
                # With initial 50-gallon tank, we can reach any station in (0, 500] that can reach destination
                reachable_from_start = [
                    i for i in range(1, n - 1)
                    if (all_nodes[i]['dist'] <= self.max_range) and can_reach_dest[i]
                ]
                if not reachable_from_start:
                    raise NoFeasibleFuelPlanException(
                        message=f"No fuel stations reachable within {int(self.max_range)} miles from start."
                    )

                # Strategy from Start:
                # Select the cheapest station within reach.
                # If tied, pick the farthest station to maximize utilization of the free initial tank.
                best_first_stop_idx = min(
                    reachable_from_start,
                    key=lambda idx: (all_nodes[idx]['price'], -all_nodes[idx]['dist'])
                )

                dist_traveled = all_nodes[best_first_stop_idx]['dist'] - curr_dist
                curr_fuel -= (dist_traveled / self.mpg)
                curr_dist = all_nodes[best_first_stop_idx]['dist']
                curr_idx = best_first_stop_idx
                continue

            # We are now at station `curr_idx`
            curr_station = all_nodes[curr_idx]['station']
            curr_price = all_nodes[curr_idx]['price']

            # Find all nodes reachable from `curr_idx` with a FULL tank
            reachable_ahead = [
                i for i in range(curr_idx + 1, n)
                if (all_nodes[i]['dist'] - curr_dist <= self.max_range + 1e-6) and can_reach_dest[i]
            ]

            if not reachable_ahead:
                raise NoFeasibleFuelPlanException(
                    message=f"Vehicle stranded at station '{curr_station.name}'. No reachable forward stations."
                )

            # Check if there is any station ahead cheaper than curr_price
            cheaper_ahead = [i for i in reachable_ahead if all_nodes[i]['station'] is not None and all_nodes[i]['price'] < curr_price]

            if cheaper_ahead:
                # Target the FIRST cheaper station
                target_idx = cheaper_ahead[0]
                dist_to_target = all_nodes[target_idx]['dist'] - curr_dist
                fuel_needed = dist_to_target / self.mpg

                if curr_fuel < fuel_needed:
                    gallons_to_buy = fuel_needed - curr_fuel
                    cost = gallons_to_buy * curr_price
                    if round(gallons_to_buy, 2) > 0.0:
                        stops.append(OptimizedFuelStop(
                            station=curr_station,
                            gallons_purchased=gallons_to_buy,
                            cost=cost
                        ))
                    curr_fuel = 0.0
                else:
                    curr_fuel -= fuel_needed

                curr_dist = all_nodes[target_idx]['dist']
                curr_idx = target_idx

            else:
                # No cheaper station reachable within max_range.
                # Is destination directly reachable within max_range?
                if total_distance - curr_dist <= self.max_range + 1e-6:
                    fuel_needed = (total_distance - curr_dist) / self.mpg
                    if curr_fuel < fuel_needed:
                        gallons_to_buy = fuel_needed - curr_fuel
                        cost = gallons_to_buy * curr_price
                        if round(gallons_to_buy, 2) > 0.0:
                            stops.append(OptimizedFuelStop(
                                station=curr_station,
                                gallons_purchased=gallons_to_buy,
                                cost=cost
                            ))
                    break
                else:
                    # Station is the cheapest in its horizon. Fill up to full tank!
                    gallons_to_buy = self.tank_capacity - curr_fuel
                    cost = gallons_to_buy * curr_price
                    if round(gallons_to_buy, 2) > 0.0:
                        stops.append(OptimizedFuelStop(
                            station=curr_station,
                            gallons_purchased=gallons_to_buy,
                            cost=cost
                        ))
                    curr_fuel = self.tank_capacity

                    # Move to the station in range that offers the lowest price (or furthest if tied)
                    candidates = [i for i in reachable_ahead if all_nodes[i]['station'] is not None]
                    if not candidates:
                        raise NoFeasibleFuelPlanException(
                            message=f"No forward station reachable from {curr_station.name}."
                        )

                    next_stop_idx = min(
                        candidates,
                        key=lambda idx: (all_nodes[idx]['price'], -all_nodes[idx]['dist'])
                    )
                    dist_to_next = all_nodes[next_stop_idx]['dist'] - curr_dist
                    curr_fuel -= (dist_to_next / self.mpg)
                    curr_dist = all_nodes[next_stop_idx]['dist']
                    curr_idx = next_stop_idx

        # Calculate totals
        total_purchased = sum(s.gallons_purchased for s in stops)
        total_cost = sum(s.cost for s in stops)

        logger.info(
            "Optimization complete: %d fuel stops, %.2f gal purchased, $%.2f total cost.",
            len(stops), total_purchased, total_cost
        )

        return FuelPlan(
            total_distance_miles=total_distance,
            total_gallons_consumed=total_gallons_consumed,
            total_gallons_purchased=round(total_purchased, 2),
            total_fuel_cost=round(total_cost, 2),
            stops=stops
        )
