"""
API integration and view tests for FuelRoute endpoints:
- POST /api/v1/routes/optimize/
- GET /health/
- GET /demo/
"""
from unittest.mock import patch
import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

from routes.exceptions import RoutingProviderUnavailableException, LocationNotFoundException


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestHealthCheckEndpoint:
    def test_health_check_returns_ok(self, client):
        response = client.get('/health/')
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'ok'
        assert data['redis'] in ('ok', 'degraded', 'unavailable')
        assert data['fuel_dataset']['loaded'] is True
        assert data['fuel_dataset']['station_count'] > 5000

    def test_liveness_check_returns_ok(self, client):
        response = client.get('/health/live/')
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'ok'

    def test_readiness_check_returns_ok(self, client):
        response = client.get('/health/ready/')
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data['status'] == 'ok'


class TestDemoEndpoint:
    def test_demo_page_renders_html(self, client):
        response = client.get('/demo/')
        assert response.status_code == status.HTTP_200_OK
        assert b'FuelRoute' in response.content
        assert b'maplibre' in response.content.lower() or b'leaflet' in response.content.lower()


class TestRouteOptimizeEndpoint:
    def test_missing_start_returns_400(self, client):
        response = client.post('/api/v1/routes/optimize/', {'finish': 'Chicago, IL'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert 'error' in data
        assert 'start' in data['details']

    def test_missing_finish_returns_400(self, client):
        response = client.post('/api/v1/routes/optimize/', {'start': 'New York, NY'}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert 'error' in data
        assert 'finish' in data['details']

    def test_identical_locations_returns_400(self, client):
        response = client.post(
            '/api/v1/routes/optimize/',
            {'start': 'New York, NY', 'finish': 'new york, ny'},
            format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert 'finish' in data['details']

    def test_location_outside_usa_returns_400(self, client):
        response = client.post(
            '/api/v1/routes/optimize/',
            {
                'start': {'latitude': 48.8566, 'longitude': 2.3522},  # Paris
                'finish': {'latitude': 40.7128, 'longitude': -74.0060}
            },
            format='json'
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    @patch('routes.services.routing_service.OSRMRoutingService.get_route')
    def test_optimize_short_route_success(self, mock_route, mock_geo, client):
        # Mock geocoding
        mock_geo.side_effect = lambda query: (
            (40.7128, -74.0060, 'New York, NY') if 'New York' in query else (40.0000, -75.0000, 'Philadelphia, PA')
        )
        # Mock route 95 miles
        mock_route.return_value = {
            'distance_miles': 95.0,
            'duration_minutes': 110.0,
            'geometry': {
                'type': 'LineString',
                'coordinates': [[-74.0060, 40.7128], [-75.0000, 40.0000]]
            }
        }

        payload = {'start': 'New York, NY', 'finish': 'Philadelphia, PA'}
        response = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data['vehicle']['max_range_miles'] == 500
        assert data['vehicle']['mpg'] == 10
        assert data['vehicle']['starting_tank'] == 'full'
        assert data['route']['distance_miles'] == 95.0
        # Under 500 miles -> 0 fuel stops
        assert len(data['fuel_stops']) == 0
        assert data['fuel_summary']['total_gallons_consumed'] == 9.5
        assert data['fuel_summary']['total_gallons_purchased'] == 0.0
        assert data['fuel_summary']['total_fuel_cost'] == 0.0

    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    @patch('routes.services.routing_service.OSRMRoutingService.get_route')
    def test_routing_provider_failure_returns_502(self, mock_route, mock_geo, client):
        mock_geo.side_effect = lambda query: (40.7128, -74.0060, 'New York, NY')
        mock_route.side_effect = RoutingProviderUnavailableException(message="OSRM timeout")

        payload = {
            'start': {'latitude': 40.7128, 'longitude': -74.0060},
            'finish': {'latitude': 41.8781, 'longitude': -87.6298}
        }
        response = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        data = response.json()
        assert data['error'] == 'RoutingProviderUnavailable'

    @patch('routes.services.geocoding_service.NominatimGeocoder.geocode')
    def test_unknown_location_returns_404(self, mock_geo, client):
        mock_geo.side_effect = LocationNotFoundException(message="Unknown location")

        payload = {'start': 'UnresolvableAlienPlace999', 'finish': 'Chicago, IL'}
        response = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert data['error'] == 'LocationNotFound'
