"""
Django AppConfig for routes application.
Initializes the in-memory station service upon startup.
"""
import sys
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class RoutesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'routes'

    def ready(self):
        # Avoid running station loading during migrations or inspectdb commands
        if any(cmd in sys.argv for cmd in ['makemigrations', 'migrate', 'collectstatic', 'prepare_fuel_data']):
            return

        try:
            from routes.services.station_service import StationService
            StationService.get_instance()
        except Exception as exc:
            logger.warning("Station service pre-load during ready() failed: %s", exc)
