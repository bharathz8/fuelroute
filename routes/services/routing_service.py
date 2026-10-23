"""
Routing service interface and OSRM implementation.
Handles route calculation, GeoJSON extraction, distance/duration conversion, and caching.
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
import requests
from django.conf import settings
from django.core.cache import cache

from routes.exceptions import RoutingProviderUnavailableException

logger = logging.getLogger(__name__)

METERS_TO_MILES = 0.00062137119223733


class BaseRouter(ABC):
    """Abstract routing service provider."""

    @abstractmethod
    def get_route(self, start_coords: Tuple[float, float], finish_coords: Tuple[float, float]) -> Dict[str, Any]:
        """
        Calculates a driving route between two points.
        Returns dict containing:
            - distance_miles: float
            - duration_minutes: float
            - geometry: dict (GeoJSON LineString)
        """
        pass


class OSRMRoutingService(BaseRouter):
    """OSRM (Open Source Routing Machine) free public routing provider."""

    def __init__(self, base_url: str = None, timeout: float = None):
        self.base_url = base_url or getattr(settings, 'OSRM_BASE_URL', 'https://router.project-osrm.org')
        self.timeout = timeout or getattr(settings, 'HTTP_TIMEOUT_SECONDS', 10.0)

    def get_route(self, start_coords: Tuple[float, float], finish_coords: Tuple[float, float]) -> Dict[str, Any]:
        start_lat, start_lon = start_coords
        finish_lat, finish_lon = finish_coords

        # OSRM expects coordinates in {lon},{lat} order
        url = (
            f"{self.base_url}/route/v1/driving/"
            f"{start_lon:.6f},{start_lat:.6f};{finish_lon:.6f},{finish_lat:.6f}"
        )
        params = {
            'overview': 'full',
            'geometries': 'geojson',
            'steps': 'false',
        }
        headers = {
            'User-Agent': 'FuelRouteAPI/1.0 (assessment; contact@example.com)',
            'Accept': 'application/json',
        }

        logger.debug("Requesting OSRM route: %s", url)
        timeout_tuple = (3.0, self.timeout)

        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout_tuple)
        except requests.exceptions.Timeout as exc:
            logger.error("OSRM request timed out: %s", exc)
            raise RoutingProviderUnavailableException(
                message="External routing service request timed out."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("OSRM connection or DNS failure: %s", exc)
            raise RoutingProviderUnavailableException(
                message="Unable to connect to external routing service."
            ) from exc
        except requests.RequestException as exc:
            logger.error("OSRM network request failed: %s", exc)
            raise RoutingProviderUnavailableException(
                message="External routing service is currently unreachable."
            ) from exc

        if response.status_code == 429:
            logger.warning("OSRM rate limit exceeded (HTTP 429)")
            raise RoutingProviderUnavailableException(
                message="External routing service rate limit reached. Please try again shortly."
            )
        elif response.status_code in (500, 502, 503, 504):
            logger.error("OSRM server error %s: %s", response.status_code, response.text[:200])
            raise RoutingProviderUnavailableException(
                message=f"External routing service is temporarily unavailable (status {response.status_code})."
            )
        elif response.status_code != 200:
            logger.error("OSRM returned status %s: %s", response.status_code, response.text[:200])
            raise RoutingProviderUnavailableException(
                message=f"External routing service returned error status {response.status_code}."
            )

        try:
            data = response.json()
        except ValueError as json_err:
            logger.error("Malformed JSON received from OSRM: %s", json_err)
            raise RoutingProviderUnavailableException(
                message="Malformed response from routing service."
            ) from json_err

        if data.get('code') != 'Ok' or not data.get('routes'):
            code_msg = data.get('message', data.get('code', 'No route found'))
            logger.warning("OSRM failed to find route: %s", code_msg)
            raise RoutingProviderUnavailableException(
                message=f"Routing provider could not compute a route between locations: {code_msg}"
            )

        primary_route = data['routes'][0]
        distance_meters = float(primary_route.get('distance', 0.0))
        duration_seconds = float(primary_route.get('duration', 0.0))
        geometry = primary_route.get('geometry', {'type': 'LineString', 'coordinates': []})

        distance_miles = round(distance_meters * METERS_TO_MILES, 2)
        duration_minutes = round(duration_seconds / 60.0, 1)

        return {
            'distance_miles': distance_miles,
            'duration_minutes': duration_minutes,
            'geometry': geometry,
        }


class RoutingService:
    """
    Facade routing service with Redis caching.
    Ensures identical coordinate pairs do not trigger repeated external HTTP calls.
    """

    def __init__(self, provider: BaseRouter = None):
        self.provider = provider or OSRMRoutingService()
        self.ttl = getattr(settings, 'CACHE_TTL_SECONDS', 3600)

    def get_route(self, start_coords: Tuple[float, float], finish_coords: Tuple[float, float]) -> Dict[str, Any]:
        start_lat, start_lon = start_coords
        finish_lat, finish_lon = finish_coords

        cache_key = f"route:{start_lat:.4f}:{start_lon:.4f}:{finish_lat:.4f}:{finish_lon:.4f}"

        # 1. Check Redis cache
        try:
            cached_data = cache.get(cache_key)
            if cached_data:
                logger.info("Routing cache HIT for %s", cache_key)
                return cached_data
        except Exception as exc:
            logger.warning("Cache retrieval error for routing: %s", exc)

        logger.info("Routing cache MISS for %s", cache_key)

        # 2. Call routing provider
        route_data = self.provider.get_route(start_coords, finish_coords)

        # 3. Cache the result
        try:
            cache.set(cache_key, route_data, timeout=self.ttl)
        except Exception as exc:
            logger.warning("Failed to store route in cache: %s", exc)

        return route_data
