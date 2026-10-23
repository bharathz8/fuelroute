"""
Unit tests for the StationService, spatial grid indexing, and corridor filtering.
"""
import pytest
from routes.services.station_service import StationService, FuelStation, haversine_miles


class TestStationService:
    def setup_method(self):
        self.service = StationService.get_instance()

    def test_station_service_loaded(self):
        assert self.service.is_loaded
        assert len(self.service.stations) > 5000
        assert len(self.service.grid) > 1000

    def test_deduplication_integrity(self):
        # Verify no duplicate OPIS IDs exist in the loaded stations
        opis_ids = [s.opis_id for s in self.service.stations]
        assert len(opis_ids) == len(set(opis_ids))

    def test_station_prices_positive(self):
        # Verify all loaded stations have strictly positive, numeric prices
        for s in self.service.stations:
            assert isinstance(s.price, float)
            assert s.price > 0.0

    def test_haversine_formula(self):
        # Known distance between NYC (40.7128, -74.0060) and Chicago (41.8781, -87.6298) is ~711 miles great circle
        dist = haversine_miles(40.7128, -74.0060, 41.8781, -87.6298)
        assert 700.0 < dist < 720.0

    def test_offline_city_lookup(self):
        coords = self.service.lookup_city_coordinates("Chicago, IL")
        assert coords is not None
        lat, lon = coords
        assert 41.0 < lat < 43.0
        assert -88.5 < lon < -87.0

    def test_route_corridor_candidate_filtering(self):
        # Create a synthetic straight route polyline between (40.0, -80.0) and (40.0, -82.0)
        # Length is roughly ~106 miles
        # OSRM coordinates are in [lon, lat] format
        route_coords = [
            [-80.0, 40.0],
            [-81.0, 40.0],
            [-82.0, 40.0],
        ]
        total_dist = haversine_miles(40.0, -80.0, 40.0, -82.0)

        # Candidates along this route
        candidates = self.service.find_candidate_stations_along_route(
            geometry_coords=route_coords,
            total_route_distance=total_dist,
            corridor_miles=25.0
        )

        assert isinstance(candidates, list)
        for c in candidates:
            # Must have distance_along_route assigned
            assert 0.0 < c.distance_along_route < total_dist
            # Must be within corridor
            assert c.corridor_offset_miles <= 25.0

        # Candidates must be strictly sorted by progress along the route
        for i in range(1, len(candidates)):
            assert candidates[i].distance_along_route >= candidates[i - 1].distance_along_route
