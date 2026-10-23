"""
Tests for Input Validation & Security (Phase 6 & 7).
Verifies rejection of oversized input, control character injection,
out-of-bound geographic locations (Mexico, Canada, international),
and presence of security headers.
"""
import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

from routes.services.geocoding_service import is_within_usa


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestSecurityValidation:
    def test_oversized_location_string_rejected(self, client):
        """Reject location strings longer than 200 characters."""
        long_name = "A" * 250
        res = client.post('/api/v1/routes/optimize/', {'start': long_name, 'finish': 'Chicago, IL'}, format='json')
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert data['error'] == 'InvalidRequest'
        assert 'start' in data['details']

    def test_log_injection_control_characters_rejected(self, client):
        """Reject strings with newlines, carriage returns, or null bytes."""
        malicious_str = "New York, NY\r\nCRLF_INJECTION_LOG_ENTRY"
        res = client.post('/api/v1/routes/optimize/', {'start': malicious_str, 'finish': 'Chicago, IL'}, format='json')
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert data['error'] == 'InvalidRequest'

    def test_precise_usa_boundary_checks(self):
        """Test is_within_usa accurately rejects non-US coordinates."""
        # Valid US coordinates
        assert is_within_usa(40.7128, -74.0060) is True   # New York, NY
        assert is_within_usa(34.0522, -118.2437) is True  # Los Angeles, CA
        assert is_within_usa(25.7617, -80.1918) is True   # Miami, FL
        assert is_within_usa(47.6062, -122.3321) is True  # Seattle, WA
        assert is_within_usa(61.2181, -149.9003) is True  # Anchorage, AK
        assert is_within_usa(21.3069, -157.8583) is True  # Honolulu, HI

        # Foreign locations that should be rejected
        assert is_within_usa(19.4326, -99.1332) is False   # Mexico City, Mexico
        assert is_within_usa(20.9674, -89.5926) is False   # Merida, Mexico (Yucatan)
        assert is_within_usa(51.5074, -0.1278) is False    # London, UK
        assert is_within_usa(48.8566, 2.3522) is False     # Paris, France
        assert is_within_usa(35.6762, 139.6503) is False   # Tokyo, Japan
        assert is_within_usa(10.0000, -40.0000) is False   # Atlantic Ocean

    def test_absurd_coordinate_ranges_rejected(self, client):
        """Reject coordinate values out of latitude [-90, 90] and longitude [-180, 180]."""
        payload = {
            'start': {'latitude': 999.0, 'longitude': -74.0},
            'finish': {'latitude': 40.0, 'longitude': -80.0}
        }
        res = client.post('/api/v1/routes/optimize/', payload, format='json')
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_security_headers_present(self, client):
        """Verify essential production security headers on API responses."""
        res = client.get('/health/')
        assert res.status_code == status.HTTP_200_OK
        # X-Content-Type-Options: nosniff
        assert res.headers.get('X-Content-Type-Options') == 'nosniff'
        # X-Frame-Options: DENY
        assert res.headers.get('X-Frame-Options') == 'DENY'
