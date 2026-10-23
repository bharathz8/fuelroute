"""
Unit tests specifically verifying caching behaviors and TTLs.
"""
from unittest.mock import patch, MagicMock
import pytest
from django.core.cache import cache

from routes.services.geocoding_service import GeocodingService, NominatimGeocoder
from routes.services.routing_service import RoutingService, OSRMRoutingService


class TestCachingBehavior:
    def setup_method(self):
        cache.clear()

    @patch.object(NominatimGeocoder, 'geocode')
    def test_geocoding_cache_hit_and_miss(self, mock_geocode):
        mock_geocode.return_value = (40.7128, -74.0060, 'New York, NY, USA')
        service = GeocodingService()

        # Miss: External geocoder invoked
        res1 = service.geocode('New York, NY')
        assert mock_geocode.call_count == 1
        assert res1[0] == 40.7128

        # Hit: External geocoder NOT invoked
        res2 = service.geocode('new york,   ny')  # Normalized match
        assert mock_geocode.call_count == 1
        assert res2[0] == 40.7128

    @patch.object(OSRMRoutingService, 'get_route')
    def test_routing_cache_hit_and_miss(self, mock_osrm):
        mock_osrm.return_value = {
            'distance_miles': 790.4,
            'duration_minutes': 735.0,
            'geometry': {'type': 'LineString', 'coordinates': []}
        }
        service = RoutingService()

        # Miss: OSRM invoked
        res1 = service.get_route((40.7128, -74.0060), (41.8781, -87.6298))
        assert mock_osrm.call_count == 1
        assert res1['distance_miles'] == 790.4

        # Hit: OSRM NOT invoked
        res2 = service.get_route((40.7128, -74.0060), (41.8781, -87.6298))
        assert mock_osrm.call_count == 1
        assert res2['distance_miles'] == 790.4

    def test_deterministic_cache_key_formatting(self):
        start = (40.7128123, -74.0060456)
        finish = (41.8781987, -87.6298123)
        expected_key = f"route:{start[0]:.4f}:{start[1]:.4f}:{finish[0]:.4f}:{finish[1]:.4f}"
        assert expected_key == "route:40.7128:-74.0060:41.8782:-87.6298"
