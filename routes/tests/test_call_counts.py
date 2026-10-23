"""
Tests for External Routing & Geocoding API Call Efficiency (Phase 3).
Verifies that:
- Cold cache text requests make at most 2 geocode calls and 1 routing call.
- Coordinate requests make 0 geocode calls and 1 routing call.
- Cache hits make 0 external network calls.
- There are ZERO per-station external HTTP calls.
"""
from unittest.mock import patch, MagicMock
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


class TestExternalCallEfficiency:
    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    @patch('routes.services.routing_service.OSRMRoutingService.get_route')
    def test_text_locations_call_counts(self, mock_route, mock_geo, client):
        mock_geo.side_effect = lambda query: (
            (40.7128, -74.0060, 'New York, NY') if 'New York' in query else (41.8781, -87.6298, 'Chicago, IL')
        )
        mock_route.return_value = {
            'distance_miles': 790.0,
            'duration_minutes': 740.0,
            'geometry': {
                'type': 'LineString',
                'coordinates': [[-74.0060, 40.7128], [-80.0, 41.0], [-87.6298, 41.8781]]
            }
        }

        # 1. COLD CACHE: First Request
        payload = {'start': 'New York, NY', 'finish': 'Chicago, IL'}
        res = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res.status_code == status.HTTP_200_OK

        # Assert exactly 2 geocode calls (start and finish) and 1 routing call
        assert mock_geo.call_count == 2
        assert mock_route.call_count == 1

        # 2. WARM CACHE: Second Identical Request
        res2 = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res2.status_code == status.HTTP_200_OK

        # Assert no additional external calls occurred (cached in Redis)
        assert mock_geo.call_count == 2
        assert mock_route.call_count == 1

    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    @patch('routes.services.routing_service.OSRMRoutingService.get_route')
    def test_coordinate_locations_zero_geocoding_calls(self, mock_route, mock_geo, client):
        mock_route.return_value = {
            'distance_miles': 300.0,
            'duration_minutes': 320.0,
            'geometry': {
                'type': 'LineString',
                'coordinates': [[-74.0060, 40.7128], [-77.0369, 38.9072]]
            }
        }

        # 1. Coordinate Input: Cold Cache
        payload = {
            'start': {'latitude': 40.7128, 'longitude': -74.0060},
            'finish': {'latitude': 38.9072, 'longitude': -77.0369}
        }
        res = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res.status_code == status.HTTP_200_OK

        # 0 geocoding calls, exactly 1 routing call
        assert mock_geo.call_count == 0
        assert mock_route.call_count == 1

        # 2. Coordinate Input: Warm Cache
        res2 = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res2.status_code == status.HTTP_200_OK

        # Still 0 geocoding calls and 1 routing call (route came from cache)
        assert mock_geo.call_count == 0
        assert mock_route.call_count == 1

    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    @patch('routes.services.routing_service.OSRMRoutingService.get_route')
    def test_zero_per_station_external_calls(self, mock_route, mock_geo, client):
        """
        Verify that candidate stations and stops do NOT trigger individual routing calls.
        Even for a route with hundreds of candidate stations, external routing calls remain exactly 1.
        """
        mock_geo.side_effect = lambda query: (40.7128, -74.0060, 'Start')
        # Realistic coordinates along I-80 corridor from NY to Chicago (~790 miles)
        coords = [
            [-74.0060, 40.7128],
            [-77.0000, 41.0000],
            [-80.6474, 41.0986],
            [-83.5000, 41.5000],
            [-87.6298, 41.8781]
        ]
        mock_route.return_value = {
            'distance_miles': 790.0,
            'duration_minutes': 740.0,
            'geometry': {'type': 'LineString', 'coordinates': coords}
        }

        payload = {
            'start': {'latitude': 40.7128, 'longitude': -74.0060},
            'finish': {'latitude': 41.8781, 'longitude': -87.6298}
        }
        res = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        # Route has stops and candidates, yet exactly 1 routing call total
        assert data['meta']['candidate_station_count'] > 0
        assert data['meta']['fuel_stop_count'] >= 1
        assert mock_route.call_count == 1
        assert mock_geo.call_count == 0
