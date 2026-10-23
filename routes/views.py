"""
Views for FuelRoute API:
- RouteOptimizeView: POST /api/v1/routes/optimize/
- HealthCheckView: GET /health/
- DemoView: GET /demo/
"""
import logging
from django.shortcuts import render
from django.views import View
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError

from routes.serializers import RouteOptimizeRequestSerializer
from routes.services.route_service import RouteService
from routes.services.station_service import StationService
from routes.exceptions import (
    FuelRouteException,
    LocationNotFoundException,
    InvalidLocationException,
    RoutingProviderUnavailableException,
    GeocodingProviderUnavailableException,
    NoFeasibleFuelPlanException,
)

logger = logging.getLogger(__name__)


import time
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator


@method_decorator(csrf_exempt, name='dispatch')
class RouteOptimizeView(APIView):
    """
    POST /api/v1/routes/optimize/
    Calculates the driving route between start and finish, identifies candidate fuel stations,
    and returns an optimal sequence of refueling stops minimizing fuel costs under vehicle constraints.
    Rate limited to prevent denial-of-service and public routing API quota exhaustion.
    """

    def post(self, request, *args, **kwargs):
        start_time = time.time()
        serializer = RouteOptimizeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Invalid route optimize request: %s", serializer.errors)
            return Response(
                {
                    'error': 'InvalidRequest',
                    'message': 'Validation failed for route optimization request.',
                    'details': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        start = serializer.validated_data['start']
        finish = serializer.validated_data['finish']

        try:
            route_service = RouteService()
            result = route_service.optimize_route(start, finish)
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.info(
                "Route optimization succeeded in %.1fms | stops: %d | cost: $%.2f | candidates: %d",
                elapsed_ms,
                result['meta']['fuel_stop_count'],
                result['fuel_summary']['total_fuel_cost'],
                result['meta']['candidate_station_count']
            )
            return Response(result, status=status.HTTP_200_OK)

        except FuelRouteException as exc:
            logger.warning("Domain exception in RouteOptimizeView: %s (%s)", exc.default_code, exc.detail)
            return Response(exc.detail, status=exc.status_code)

        except ValidationError as exc:
            return Response(
                {
                    'error': 'InvalidRequest',
                    'message': 'Validation failed for route optimization request.',
                    'details': exc.detail
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as exc:
            logger.exception("Unhandled error during route optimization: %s", exc)
            return Response(
                {
                    'error': 'InternalServerError',
                    'message': 'An unexpected error occurred while calculating the optimal route. Please try again later.'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class HealthCheckView(APIView):
    """
    GET /health/
    Health and readiness check reporting status of API, Redis cache, and in-memory fuel station data.
    Unthrottled to ensure monitoring systems are never rate-limited.
    """
    throttle_classes = []

    def get(self, request, *args, **kwargs):
        # 1. Check Redis connectivity
        redis_status = "ok"
        try:
            cache.set("__health_check__", 1, timeout=5)
            val = cache.get("__health_check__")
            if val != 1:
                redis_status = "degraded"
        except Exception as exc:
            logger.warning("Redis health check failed: %s", exc)
            redis_status = "unavailable"

        # 2. Check Station Dataset
        station_svc = StationService.get_instance()
        station_count = len(station_svc.stations)
        dataset_loaded = station_svc.is_loaded and station_count > 0

        overall_status = "ok" if dataset_loaded else "degraded"

        return Response(
            {
                'status': overall_status,
                'redis': redis_status,
                'fuel_dataset': {
                    'loaded': dataset_loaded,
                    'station_count': station_count
                }
            },
            status=status.HTTP_200_OK if overall_status == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
        )


class LivenessCheckView(APIView):
    """
    GET /health/live/
    Ultra-lightweight liveness probe indicating process is running.
    Never checks external dependencies or databases.
    """
    throttle_classes = []

    def get(self, request, *args, **kwargs):
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class ReadinessCheckView(HealthCheckView):
    """
    GET /health/ready/
    Readiness probe verifying that Redis cache and fuel station datasets are loaded.
    """
    pass


class DemoView(View):
    """
    GET /demo/
    Serves the MapLibre interactive route and fuel stop visualization dashboard.
    """

    def get(self, request, *args, **kwargs):
        from django.conf import settings
        map_style_url = getattr(settings, 'MAP_STYLE_URL', 'https://tiles.openfreemap.org/styles/liberty')
        return render(request, 'demo.html', {'map_style_url': map_style_url})
