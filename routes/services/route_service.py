"""
Route Service Orchestrator.
Coordinates Geocoding -> Routing -> Corridor Station Filtering -> Fuel Optimization.
"""
import logging
from typing import Dict, Any, Union
from django.conf import settings

from routes.services.geocoding_service import GeocodingService
from routes.services.routing_service import RoutingService
from routes.services.station_service import StationService
from routes.services.fuel_optimizer import FuelOptimizer

logger = logging.getLogger(__name__)


class RouteService:
    """
    Coordinates end-to-end route optimization pipeline.
    """

    def __init__(
        self,
        geocoding_service: GeocodingService = None,
        routing_service: RoutingService = None,
        station_service: StationService = None,
        fuel_optimizer: FuelOptimizer = None,
    ):
        self.station_service = station_service or StationService.get_instance()
        self.geocoding_service = geocoding_service or GeocodingService(
            offline_station_service=self.station_service
        )
        self.routing_service = routing_service or RoutingService()
        self.fuel_optimizer = fuel_optimizer or FuelOptimizer(
            max_range_miles=getattr(settings, 'MAX_RANGE_MILES', 500.0),
            mpg=getattr(settings, 'MPG', 10.0),
        )
        self.corridor_miles = getattr(settings, 'ROUTE_CORRIDOR_MILES', 25.0)

    def optimize_route(self, start_input: Union[str, Dict[str, Any]], finish_input: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Executes the complete route optimization pipeline.
        """
        logger.info("Starting route optimization from %s to %s", start_input, finish_input)

        # 1. Resolve Start & Finish Locations
        start_lat, start_lon, start_label = self.geocoding_service.resolve_location(start_input, field_name="start")
        finish_lat, finish_lon, finish_label = self.geocoding_service.resolve_location(finish_input, field_name="finish")

        # 2. Get Driving Route & Geometry (1 external routing call or 0 if cached)
        route_data = self.routing_service.get_route(
            (start_lat, start_lon),
            (finish_lat, finish_lon)
        )
        total_distance = route_data['distance_miles']
        duration_minutes = route_data['duration_minutes']
        geometry = route_data['geometry']
        coordinates = geometry.get('coordinates', [])

        # 3. Filter Candidate Fuel Stations along the Route Corridor (sub-millisecond in-memory)
        candidates = self.station_service.find_candidate_stations_along_route(
            geometry_coords=coordinates,
            total_route_distance=total_distance,
            corridor_miles=self.corridor_miles
        )

        # 4. Run Fuel Optimization Algorithm
        fuel_plan = self.fuel_optimizer.optimize(
            total_distance=total_distance,
            candidate_stations=candidates
        )

        # 5. Build Final Response Structure
        # Format request display
        req_start = start_input if isinstance(start_input, str) else {'latitude': start_lat, 'longitude': start_lon}
        req_finish = finish_input if isinstance(finish_input, str) else {'latitude': finish_lat, 'longitude': finish_lon}

        return {
            'request': {
                'start': req_start,
                'finish': req_finish,
            },
            'vehicle': {
                'max_range_miles': int(self.fuel_optimizer.max_range),
                'mpg': int(self.fuel_optimizer.mpg),
                'starting_tank': getattr(settings, 'STARTING_TANK', 'full'),
            },
            'route': {
                'start_resolved': start_label,
                'finish_resolved': finish_label,
                'distance_miles': total_distance,
                'duration_minutes': duration_minutes,
                'geometry': geometry,
            },
            'fuel_stops': [s.to_dict() for s in fuel_plan.stops],
            'fuel_summary': {
                'total_gallons_consumed': fuel_plan.total_gallons_consumed,
                'total_gallons_purchased': fuel_plan.total_gallons_purchased,
                'total_fuel_cost': fuel_plan.total_fuel_cost,
            },
            'meta': {
                'routing_provider': getattr(settings, 'ROUTING_PROVIDER', 'OSRM').upper(),
                'route_corridor_miles': self.corridor_miles,
                'candidate_station_count': len(candidates),
                'fuel_stop_count': len(fuel_plan.stops),
            }
        }
