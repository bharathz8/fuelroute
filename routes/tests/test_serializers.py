"""
Unit tests for request serializers and input validation.
"""
import pytest
from routes.serializers import RouteOptimizeRequestSerializer, CoordinateSerializer


class TestInputValidation:
    def test_valid_string_locations(self):
        data = {
            'start': 'New York, NY',
            'finish': 'Chicago, IL',
        }
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data['start'] == 'New York, NY'
        assert serializer.validated_data['finish'] == 'Chicago, IL'

    def test_valid_coordinate_locations(self):
        data = {
            'start': {'latitude': 40.7128, 'longitude': -74.0060},
            'finish': {'latitude': 41.8781, 'longitude': -87.6298},
        }
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_missing_start_location(self):
        data = {'finish': 'Chicago, IL'}
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'start' in serializer.errors

    def test_missing_finish_location(self):
        data = {'start': 'New York, NY'}
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'finish' in serializer.errors

    def test_empty_string_location(self):
        data = {'start': '   ', 'finish': 'Chicago, IL'}
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'start' in serializer.errors

    def test_identical_string_locations(self):
        data = {'start': 'Chicago, IL', 'finish': 'chicago, il'}
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'finish' in serializer.errors

    def test_identical_coordinate_locations(self):
        data = {
            'start': {'latitude': 41.8781, 'longitude': -87.6298},
            'finish': {'latitude': 41.8781, 'longitude': -87.6298},
        }
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'finish' in serializer.errors

    def test_invalid_coordinate_ranges(self):
        # Latitude > 90
        bad_lat = CoordinateSerializer(data={'latitude': 95.0, 'longitude': -74.0})
        assert not bad_lat.is_valid()

        # Longitude < -180
        bad_lon = CoordinateSerializer(data={'latitude': 40.0, 'longitude': -190.0})
        assert not bad_lon.is_valid()

    def test_coordinates_outside_usa(self):
        # London coordinates: 51.5074, -0.1278
        data = {
            'start': {'latitude': 51.5074, 'longitude': -0.1278},
            'finish': {'latitude': 40.7128, 'longitude': -74.0060},
        }
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'start' in serializer.errors

    def test_non_numeric_coordinates(self):
        data = {
            'start': {'latitude': 'not-a-number', 'longitude': -74.0060},
            'finish': {'latitude': 40.7128, 'longitude': -74.0060},
        }
        serializer = RouteOptimizeRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert 'start' in serializer.errors
