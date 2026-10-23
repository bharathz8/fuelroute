"""
Geocoding service interface and implementations.
Provides caching via Redis and fallback to offline US city coordinates.
"""
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any
import requests
from django.conf import settings
from django.core.cache import cache

from routes.exceptions import (
    LocationNotFoundException,
    InvalidLocationException,
    GeocodingProviderUnavailableException,
)

logger = logging.getLogger(__name__)

def is_within_usa(lat: float, lon: float) -> bool:
    """
    Validates if coordinates fall within the United States geographic boundaries.
    Covers the contiguous 48 states, Alaska, and Hawaii, while explicitly rejecting
    locations in Canada, Mexico, the Caribbean, and international waters.
    """
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False

    # 1. Contiguous Lower 48 States (CONUS)
    if -125.0 <= lon <= -66.5:
        # Canada northern border check (approx 49.4°N, allowance up to 49.6°N)
        if lat > 49.6:
            return False
        # East Coast / Florida down to Florida Keys (~24.5°N)
        if -82.0 <= lon <= -66.5:
            return 24.3 <= lat <= 49.6
        # Gulf Coast / South Texas border (~25.8°N at Brownsville to ~31.75°N at El Paso)
        elif -106.5 <= lon < -82.0:
            return 25.5 <= lat <= 49.6
        # Southwest border (New Mexico, Arizona, California: border is ~31.3°N to ~32.5°N)
        elif -125.0 <= lon < -106.5:
            return 31.0 <= lat <= 49.6

    # 2. Alaska
    if -179.9 <= lon <= -129.0 and 51.0 <= lat <= 71.5:
        return True

    # 3. Hawaii
    if -178.5 <= lon <= -154.5 and 18.5 <= lat <= 28.5:
        return True

    return False


class BaseGeocoder(ABC):
    """Abstract base class for geocoding providers."""

    @abstractmethod
    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        """
        Geocode a text address into (latitude, longitude, display_name).
        Returns None if not found.
        """
        pass


class NominatimGeocoder(BaseGeocoder):
    """Nominatim OpenStreetMap geocoding provider."""

    def __init__(self, base_url: str = None, user_agent: str = None, timeout: float = None):
        self.base_url = base_url or getattr(settings, 'NOMINATIM_BASE_URL', 'https://nominatim.openstreetmap.org')
        self.user_agent = user_agent or getattr(
            settings,
            'NOMINATIM_USER_AGENT',
            'FuelRouteApp-University-Assessment/1.0 (contact@fuelroute.local)'
        )
        self.timeout = timeout or getattr(settings, 'HTTP_TIMEOUT_SECONDS', 10.0)

    def geocode(self, query: str) -> Optional[Tuple[float, float, str]]:
        # Sanitize query to prevent log/query injection and strip non-printable characters
        clean_query = re.sub(r'[\r\n\t]+', ' ', query.strip())[:200]
        url = f"{self.base_url}/search"
        params = {
            'q': clean_query,
            'format': 'json',
            'limit': 1,
            'countrycodes': 'us',
        }
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'application/json',
        }

        # Use connect timeout (3.0s) and read timeout (self.timeout) to prevent hanging sockets
        timeout_tuple = (3.0, self.timeout)

        try:
            logger.debug("Calling Nominatim geocoder for query: %s", clean_query)
            response = requests.get(url, params=params, headers=headers, timeout=timeout_tuple)

            if response.status_code == 200:
                try:
                    results = response.json()
                except ValueError as json_err:
                    logger.error("Malformed JSON received from Nominatim: %s", json_err)
                    raise GeocodingProviderUnavailableException(
                        message="Malformed response from geocoding service."
                    ) from json_err

                if results and len(results) > 0:
                    first = results[0]
                    lat = float(first['lat'])
                    lon = float(first['lon'])
                    display_name = first.get('display_name', clean_query)
                    return lat, lon, display_name
                return None

            elif response.status_code == 429:
                logger.warning("Nominatim rate limit exceeded (HTTP 429) for query '%s'", clean_query)
                raise GeocodingProviderUnavailableException(
                    message="External geocoding service rate limit reached. Please try again shortly."
                )
            elif response.status_code in (500, 502, 503, 504):
                logger.warning("Nominatim returned server error HTTP %s for query '%s'", response.status_code, clean_query)
                raise GeocodingProviderUnavailableException(
                    message=f"External geocoding service is temporarily unavailable (status {response.status_code})."
                )
            else:
                logger.warning("Nominatim unexpected response HTTP %s: %s", response.status_code, response.text[:200])
                return None

        except requests.exceptions.Timeout as exc:
            logger.error("Nominatim request timed out: %s", exc)
            raise GeocodingProviderUnavailableException(
                message="External geocoding request timed out."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Nominatim connection or DNS failure: %s", exc)
            raise GeocodingProviderUnavailableException(
                message="Unable to connect to external geocoding service."
            ) from exc
        except requests.RequestException as exc:
            logger.error("Network error contacting Nominatim: %s", exc)
            raise GeocodingProviderUnavailableException(
                message="External geocoding service is currently unreachable."
            ) from exc


class GeocodingService:
    """
    Facade geocoding service that orchestrates Redis caching,
    external geocoding provider, and offline city dataset fallback.
    """

    def __init__(self, provider: BaseGeocoder = None, offline_station_service = None):
        self.provider = provider or NominatimGeocoder()
        self.offline_station_service = offline_station_service
        self.ttl = getattr(settings, 'CACHE_TTL_SECONDS', 3600)

    def resolve_location(self, location_input: Any, field_name: str = "location") -> Tuple[float, float, str]:
        """
        Resolves either a string or dict location into (lat, lon, label).
        Validates US boundary constraints.
        """
        if isinstance(location_input, dict):
            lat = location_input.get('latitude')
            lon = location_input.get('longitude')
            if lat is None or lon is None:
                raise InvalidLocationException(
                    message=f"'{field_name}' coordinate object must contain both 'latitude' and 'longitude'."
                )
            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError) as exc:
                raise InvalidLocationException(
                    message=f"'{field_name}' coordinates must be valid numbers."
                ) from exc

            if not is_within_usa(lat, lon):
                raise InvalidLocationException(
                    message=f"'{field_name}' coordinates ({lat}, {lon}) are outside the United States."
                )
            label = location_input.get('name') or f"{lat:.4f}, {lon:.4f}"
            return lat, lon, label

        if isinstance(location_input, str):
            query = location_input.strip()
            if not query:
                raise InvalidLocationException(message=f"'{field_name}' cannot be empty.")
            return self.geocode(query, field_name)

        raise InvalidLocationException(
            message=f"'{field_name}' must be an address string or a coordinate object with latitude and longitude."
        )

    def geocode(self, query: str, field_name: str = "location") -> Tuple[float, float, str]:
        """Geocodes a query string with cache and offline fallback."""
        normalized_query = re.sub(r'\s+', ' ', query.strip().lower())
        import urllib.parse
        clean_key = urllib.parse.quote_plus(normalized_query)
        cache_key = f"geocode:{clean_key}"

        # 1. Try cache
        try:
            cached_val = cache.get(cache_key)
            if cached_val:
                logger.info("Geocode cache HIT for '%s'", normalized_query)
                lat, lon, label = cached_val
                return lat, lon, label
        except Exception as exc:
            logger.warning("Cache access error in geocoding: %s", exc)

        logger.info("Geocode cache MISS for '%s'", normalized_query)

        # 2. Try primary external provider
        lat, lon, label = None, None, None
        provider_error = None
        try:
            result = self.provider.geocode(query)
            if result:
                lat, lon, label = result
        except GeocodingProviderUnavailableException as exc:
            logger.warning("Primary geocoder unavailable, attempting offline fallback: %s", exc)
            provider_error = exc

        # 3. Fallback to offline US city lookup if available
        if lat is None and self.offline_station_service:
            offline_result = self.offline_station_service.lookup_city_coordinates(query)
            if offline_result:
                lat, lon = offline_result
                label = query.strip()
                logger.info("Resolved '%s' via offline city database: (%s, %s)", query, lat, lon)

        if lat is None:
            if provider_error:
                raise provider_error
            raise LocationNotFoundException(
                message=f"Unable to resolve {field_name} location: '{query}'. Please provide a valid US city, state or address."
            )

        # Validate US boundary
        if not is_within_usa(lat, lon):
            raise InvalidLocationException(
                message=f"Resolved location for '{query}' ({lat:.4f}, {lon:.4f}) is outside the United States."
            )

        # Cache valid response
        try:
            cache.set(cache_key, (lat, lon, label), timeout=self.ttl)
        except Exception as exc:
            logger.warning("Failed to store geocode in cache: %s", exc)

        return lat, lon, label
