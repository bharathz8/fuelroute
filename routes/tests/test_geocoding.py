"""
Unit tests for geocoding service, Nominatim integration, offline fallback, and caching.
"""
from unittest.mock import patch, MagicMock
import pytest
from django.core.cache import cache

from routes.services.geocoding_service import (
    GeocodingService,
    NominatimGeocoder,
    is_within_usa,
)
from routes.exceptions import (
    LocationNotFoundException,
    InvalidLocationException,
    GeocodingProviderUnavailableException,
)
from routes.services.station_service import StationService


class TestGeocoding:
    def setup_method(self):
        cache.clear()
        self.station_service = StationService.get_instance()
        self.geocoder = GeocodingService(offline_station_service=self.station_service)

    def test_usa_bounds_checker(self):
        assert is_within_usa(40.7128, -74.0060)  # NYC
        assert is_within_usa(21.3069, -157.8583)  # Honolulu, HI
        assert is_within_usa(61.2181, -149.9003)  # Anchorage, AK
        assert not is_within_usa(48.8566, 2.3522)  # Paris, France
        assert not is_within_usa(-33.8688, 151.2093)  # Sydney, Australia

    @patch('requests.get')
    def test_nominatim_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {'lat': '40.7128', 'lon': '-74.0060', 'display_name': 'New York, NY, USA'}
        ]
        mock_get.return_value = mock_resp

        provider = NominatimGeocoder()
        lat, lon, label = provider.geocode('New York, NY')
        assert round(lat, 4) == 40.7128
        assert round(lon, 4) == -74.0060
        assert 'New York' in label

    @patch('requests.get')
    def test_nominatim_not_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_get.return_value = mock_resp

        provider = NominatimGeocoder()
        result = provider.geocode('NonExistentCityXYZ123')
        assert result is None

    @patch('requests.get')
    def test_nominatim_service_unavailable(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_get.return_value = mock_resp

        provider = NominatimGeocoder()
        with pytest.raises(GeocodingProviderUnavailableException):
            provider.geocode('Chicago, IL')

    @patch.object(NominatimGeocoder, 'geocode')
    def test_geocoding_cache_hit_prevents_duplicate_calls(self, mock_geo):
        mock_geo.return_value = (41.8781, -87.6298, 'Chicago, IL, USA')

        # First call -> cache miss, calls provider
        lat1, lon1, _ = self.geocoder.geocode('Chicago, IL')
        assert mock_geo.call_count == 1

        # Second call -> cache hit, does not call provider
        lat2, lon2, _ = self.geocoder.geocode('Chicago, IL')
        assert mock_geo.call_count == 1
        assert (lat1, lon1) == (lat2, lon2)

    def test_resolve_coordinate_object_directly(self):
        coord_dict = {'latitude': 34.0522, 'longitude': -118.2437}
        lat, lon, label = self.geocoder.resolve_location(coord_dict)
        assert round(lat, 4) == 34.0522
        assert round(lon, 4) == -118.2437

    def test_resolve_coordinate_outside_usa(self):
        coord_dict = {'latitude': 51.5074, 'longitude': -0.1278}  # London
        with pytest.raises(InvalidLocationException):
            self.geocoder.resolve_location(coord_dict)

    @patch.object(NominatimGeocoder, 'geocode', return_value=None)
    def test_offline_fallback_when_external_geocoder_fails(self, mock_geo):
        # Even if external geocoder returns None, offline station service resolves "Dallas, TX"
        lat, lon, label = self.geocoder.geocode('Dallas, TX')
        assert 32.0 < lat < 33.5
        assert -97.5 < lon < -96.0
