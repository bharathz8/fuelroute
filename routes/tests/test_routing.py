"""
Unit tests for routing service, OSRM integration, and route caching.
"""
from unittest.mock import patch, MagicMock
import pytest
from django.core.cache import cache

from routes.services.routing_service import RoutingService, OSRMRoutingService
from routes.exceptions import RoutingProviderUnavailableException


class TestRouting:
    def setup_method(self):
        cache.clear()
        self.routing_service = RoutingService()

    @patch('requests.get')
    def test_osrm_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'code': 'Ok',
            'routes': [
                {
                    'distance': 1272000.0,  # ~790.38 miles
                    'duration': 53400.0,   # ~890 minutes
                    'geometry': {
                        'type': 'LineString',
                        'coordinates': [[-74.006, 40.7128], [-87.6298, 41.8781]]
                    }
                }
            ]
        }
        mock_get.return_value = mock_resp

        provider = OSRMRoutingService()
        result = provider.get_route((40.7128, -74.006), (41.8781, -87.6298))
        assert 'distance_miles' in result
        assert 789.0 < result['distance_miles'] < 791.0
        assert result['duration_minutes'] == 890.0
        assert result['geometry']['type'] == 'LineString'

    @patch('requests.get')
    def test_osrm_provider_error_status(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_get.return_value = mock_resp

        provider = OSRMRoutingService()
        with pytest.raises(RoutingProviderUnavailableException):
            provider.get_route((40.7128, -74.006), (41.8781, -87.6298))

    @patch('requests.get')
    def test_osrm_no_route_code(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'code': 'NoRoute',
            'message': 'Impossible route across water without ferry'
        }
        mock_get.return_value = mock_resp

        provider = OSRMRoutingService()
        with pytest.raises(RoutingProviderUnavailableException):
            provider.get_route((40.7128, -74.006), (41.8781, -87.6298))

    @patch.object(OSRMRoutingService, 'get_route')
    def test_routing_cache_hit_prevents_duplicate_calls(self, mock_route):
        mock_route.return_value = {
            'distance_miles': 790.4,
            'duration_minutes': 735.0,
            'geometry': {'type': 'LineString', 'coordinates': [[-74.0, 40.7], [-87.6, 41.8]]}
        }

        # First call -> cache miss, calls provider
        res1 = self.routing_service.get_route((40.7128, -74.0060), (41.8781, -87.6298))
        assert mock_route.call_count == 1

        # Second call with same coordinates -> cache hit, provider is not called
        res2 = self.routing_service.get_route((40.7128, -74.0060), (41.8781, -87.6298))
        assert mock_route.call_count == 1
        assert res1['distance_miles'] == res2['distance_miles']

    @patch('requests.get')
    def test_osrm_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout("OSRM request timed out")
        provider = OSRMRoutingService()
        with pytest.raises(RoutingProviderUnavailableException) as exc:
            provider.get_route((40.7128, -74.006), (41.8781, -87.6298))
        assert "timed out" in str(exc.value.detail['message']).lower()

    @patch('requests.get')
    def test_osrm_rate_limit_429(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_get.return_value = mock_resp
        provider = OSRMRoutingService()
        with pytest.raises(RoutingProviderUnavailableException) as exc:
            provider.get_route((40.7128, -74.006), (41.8781, -87.6298))
        assert "rate limit" in str(exc.value.detail['message']).lower()

    @patch('requests.get')
    def test_osrm_server_error_500(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        provider = OSRMRoutingService()
        with pytest.raises(RoutingProviderUnavailableException) as exc:
            provider.get_route((40.7128, -74.006), (41.8781, -87.6298))
        assert "temporarily unavailable" in str(exc.value.detail['message']).lower()

    @patch('requests.get')
    def test_osrm_malformed_json(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_resp
        provider = OSRMRoutingService()
        with pytest.raises(RoutingProviderUnavailableException) as exc:
            provider.get_route((40.7128, -74.006), (41.8781, -87.6298))
        assert "malformed" in str(exc.value.detail['message']).lower()

    @patch('django.core.cache.cache.get')
    @patch.object(OSRMRoutingService, 'get_route')
    def test_routing_graceful_on_redis_outage(self, mock_route, mock_cache_get):
        """Verify routing continues functioning even when Redis cache throws exceptions."""
        mock_cache_get.side_effect = Exception("Redis connection refused")
        mock_route.return_value = {
            'distance_miles': 150.0,
            'duration_minutes': 140.0,
            'geometry': {'type': 'LineString', 'coordinates': [[-74.0, 40.7], [-75.0, 40.0]]}
        }
        res = self.routing_service.get_route((40.7128, -74.0060), (41.8781, -87.6298))
        assert res['distance_miles'] == 150.0
        assert mock_route.call_count == 1
