"""
Custom exception hierarchy for FuelRoute API.
"""
from rest_framework.exceptions import APIException
from rest_framework import status


class FuelRouteException(APIException):
    """Base exception for FuelRoute domain errors."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'error'

    def __init__(self, message=None, code=None, details=None):
        if message:
            self.detail = {'error': code or self.default_code, 'message': message}
            if details:
                self.detail['details'] = details
        super().__init__(self.detail, code)


class LocationNotFoundException(FuelRouteException):
    """Raised when a geocoding lookup fails to resolve an address."""
    status_code = status.HTTP_404_NOT_FOUND
    default_code = 'LocationNotFound'


class InvalidLocationException(FuelRouteException):
    """Raised when coordinates or addresses are outside USA bounds or invalid."""
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'InvalidLocation'


class RoutingProviderUnavailableException(FuelRouteException):
    """Raised when upstream routing service (e.g. OSRM) fails or times out."""
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = 'RoutingProviderUnavailable'


class GeocodingProviderUnavailableException(FuelRouteException):
    """Raised when upstream geocoding service (e.g. Nominatim) is unreachable."""
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = 'GeocodingProviderUnavailable'


class NoFeasibleFuelPlanException(FuelRouteException):
    """Raised when route cannot be completed within 500-mile range constraints."""
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = 'NoFeasibleFuelPlan'


def custom_exception_handler(exc, context):
    """
    Standardized REST Framework exception handler.
    Ensures uniform error JSON responses across throttling, validation, domain, and server errors:
    {
        "error": "ErrorType",
        "message": "Human-readable description",
        "details": ... (optional)
    }
    """
    import logging
    from rest_framework.views import exception_handler
    from rest_framework.exceptions import Throttled, ValidationError
    from rest_framework.response import Response

    logger = logging.getLogger('routes.exceptions')

    # Handle Rate Limiting (429)
    if isinstance(exc, Throttled):
        wait_seconds = int(exc.wait) if exc.wait is not None else 60
        headers = {'Retry-After': str(wait_seconds)}
        return Response(
            {
                'error': 'RateLimitExceeded',
                'message': f'Too many requests. Please try again in {wait_seconds} seconds.'
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers=headers
        )

    # Handle Domain FuelRoute Exceptions
    if isinstance(exc, FuelRouteException):
        logger.warning("Domain exception: %s: %s", exc.default_code, exc.detail)
        return Response(exc.detail, status=exc.status_code)

    # Handle DRF Validation Errors (400)
    if isinstance(exc, ValidationError):
        return Response(
            {
                'error': 'InvalidRequest',
                'message': 'Validation failed for route optimization request.',
                'details': exc.detail
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    # Delegate to default DRF handler
    response = exception_handler(exc, context)

    if response is not None:
        # Wrap DRF built-in exceptions (e.g. MethodNotAllowed, ParseError)
        err_msg = str(response.data.get('detail', 'An API error occurred.')) if isinstance(response.data, dict) else str(response.data)
        return Response(
            {
                'error': exc.__class__.__name__,
                'message': err_msg
            },
            status=response.status_code
        )

    # Unhandled server exception: Log server-side and hide stack trace from clients
    logger.exception("Unhandled server exception in API: %s", exc)
    return Response(
        {
            'error': 'InternalServerError',
            'message': 'An unexpected error occurred while calculating the optimal route. Please try again later.'
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
