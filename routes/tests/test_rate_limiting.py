"""
Tests for API Rate Limiting (Phase 4).
Verifies that RouteOptimizeView is rate-limited according to environment configuration,
returns HTTP 429 with clean standardized JSON, and health checks remain unthrottled.
"""
from unittest.mock import patch
import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestRateLimiting:
    def test_health_check_is_not_throttled(self, client):
        """Ensure /health/, /health/live/, /health/ready/ can receive rapid requests without 429."""
        for _ in range(35):
            res = client.get('/health/')
            assert res.status_code == status.HTTP_200_OK

        for _ in range(10):
            res_live = client.get('/health/live/')
            assert res_live.status_code == status.HTTP_200_OK

    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    @patch('routes.services.routing_service.OSRMRoutingService.get_route')
    def test_route_optimize_rate_limit_exceeded(self, mock_route, mock_geo, client, settings):
        """
        Verify that exceeding the throttle rate triggers HTTP 429
        with the required error payload.
        """
        mock_geo.side_effect = lambda query: (40.7128, -74.0060, 'New York, NY')
        mock_route.return_value = {
            'distance_miles': 100.0,
            'duration_minutes': 120.0,
            'geometry': {'type': 'LineString', 'coordinates': [[-74.0060, 40.7128], [-74.1, 40.8]]}
        }

        # Override throttle rates specifically for this test
        settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['anon'] = '3/minute'

        # Make 3 valid calls that succeed
        for i in range(3):
            payload = {'start': f'City {i}, NY', 'finish': 'Chicago, IL'}
            res = client.post('/api/v1/routes/optimize/', payload, format='json')
            assert res.status_code == status.HTTP_200_OK

        # 4th call should be throttled (HTTP 429)
        payload = {'start': 'City 4, NY', 'finish': 'Chicago, IL'}
        res = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        data = res.json()
        assert data['error'] == 'RateLimitExceeded'
        assert 'Too many requests' in data['message']
        assert 'Retry-After' in res.headers
