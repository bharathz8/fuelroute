"""
Serializers for Route Optimization API requests and responses.
"""
from typing import Any, Dict
from rest_framework import serializers
from routes.services.geocoding_service import is_within_usa


class CoordinateSerializer(serializers.Serializer):
    """Validates explicit coordinate input."""
    latitude = serializers.FloatField(
        required=True,
        min_value=-90.0,
        max_value=90.0,
        error_messages={'invalid': 'Latitude must be a valid floating point number.'}
    )
    longitude = serializers.FloatField(
        required=True,
        min_value=-180.0,
        max_value=180.0,
        error_messages={'invalid': 'Longitude must be a valid floating point number.'}
    )

    def validate(self, data):
        lat = data['latitude']
        lon = data['longitude']
        if not is_within_usa(lat, lon):
            raise serializers.ValidationError(
                f"Coordinates ({lat}, {lon}) are outside the United States boundaries."
            )
        return data


class LocationField(serializers.Field):
    """
    Flexible field that accepts either a text address string
    or a coordinate dictionary {latitude: float, longitude: float}.
    """

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, str):
            clean_str = data.strip()
            if not clean_str:
                raise serializers.ValidationError("Location string cannot be empty.")
            if len(clean_str) > 200:
                raise serializers.ValidationError("Location string exceeds maximum allowed length of 200 characters.")
            # Prevent log injection and control characters
            import re
            if re.search(r'[\r\n\x00-\x1f\x7f]', clean_str):
                raise serializers.ValidationError("Location string contains invalid control characters.")
            return clean_str
        elif isinstance(data, dict):
            coord_serializer = CoordinateSerializer(data=data)
            coord_serializer.is_valid(raise_exception=True)
            return coord_serializer.validated_data
        else:
            raise serializers.ValidationError(
                "Location must be an address string (e.g. 'New York, NY') or a coordinate object "
                "{'latitude': 40.7128, 'longitude': -74.0060}."
            )

    def to_representation(self, value: Any) -> Any:
        return value


class RouteOptimizeRequestSerializer(serializers.Serializer):
    """
    Validates input for POST /api/v1/routes/optimize/
    """
    start = LocationField(required=True, error_messages={'required': 'Start location is required.'})
    finish = LocationField(required=True, error_messages={'required': 'Finish destination is required.'})

    def validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        start = data.get('start')
        finish = data.get('finish')

        # Check identical string locations
        if isinstance(start, str) and isinstance(finish, str):
            if start.strip().lower() == finish.strip().lower():
                raise serializers.ValidationError({
                    'finish': "Start and finish locations cannot be identical."
                })

        # Check identical coordinate locations
        if isinstance(start, dict) and isinstance(finish, dict):
            lat_diff = abs(start['latitude'] - finish['latitude'])
            lon_diff = abs(start['longitude'] - finish['longitude'])
            if lat_diff < 0.0001 and lon_diff < 0.0001:
                raise serializers.ValidationError({
                    'finish': "Start and finish coordinates cannot be identical."
                })

        return data
