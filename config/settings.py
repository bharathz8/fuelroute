"""
Django settings for FuelRoute API project.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present
load_dotenv(BASE_DIR / '.env')

DEBUG = os.environ.get('DEBUG', '0').lower() in ('1', 'true', 'yes')

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-fuelroute-dev-key-change-in-production-random-abc-123'
)

default_hosts = 'localhost,127.0.0.1,testserver,web'
ALLOWED_HOSTS = [host.strip() for host in os.environ.get('ALLOWED_HOSTS', default_hosts).split(',') if host.strip()]

INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'routes.apps.RoutesConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database: Minimal sqlite database for internal needs if required
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Redis Caching with graceful degradation
REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
CACHE_TTL_SECONDS = int(os.environ.get('CACHE_TTL_SECONDS', '3600'))

import sys
TESTING = 'pytest' in sys.modules or any('test' in arg for arg in sys.argv)

if TESTING:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-fuelroute-cache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'IGNORE_EXCEPTIONS': True,  # Ensures Redis downtime never breaks API functionality
                'SOCKET_CONNECT_TIMEOUT': 2,
                'SOCKET_TIMEOUT': 2,
            }
        }
    }

# API Rate Limiting Configuration
ANON_RATE_LIMIT = os.environ.get('ANON_RATE_LIMIT', '20/minute')
USER_RATE_LIMIT = os.environ.get('USER_RATE_LIMIT', '100/minute')

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': ANON_RATE_LIMIT,
        'user': USER_RATE_LIMIT,
    },
    'THROTTLE_CACHE': 'default',
    'EXCEPTION_HANDLER': 'routes.exceptions.custom_exception_handler',
    'UNAUTHENTICATED_USER': None,
}

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG and os.environ.get('CORS_ALLOW_ALL_ORIGINS', '0').lower() in ('1', 'true', 'yes')
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
    if origin.strip()
]

# Security Configuration for Production & Development
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_BROWSER_XSS_FILTER = True

SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', '0').lower() in ('1', 'true', 'yes')
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('SECURE_HSTS_INCLUDE_SUBDOMAINS', '0').lower() in ('1', 'true', 'yes')
SECURE_HSTS_PRELOAD = os.environ.get('SECURE_HSTS_PRELOAD', '0').lower() in ('1', 'true', 'yes')

SESSION_COOKIE_SECURE = not DEBUG and os.environ.get('SESSION_COOKIE_SECURE', '1').lower() in ('1', 'true', 'yes')
CSRF_COOKIE_SECURE = not DEBUG and os.environ.get('CSRF_COOKIE_SECURE', '1').lower() in ('1', 'true', 'yes')

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('CSRF_TRUSTED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
    if origin.strip()
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
] if (BASE_DIR / 'static').exists() else []

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- FuelRoute Domain Configuration ---
ROUTING_PROVIDER = os.environ.get('ROUTING_PROVIDER', 'osrm').lower()
OSRM_BASE_URL = os.environ.get('OSRM_BASE_URL', 'https://router.project-osrm.org').rstrip('/')

GEOCODING_PROVIDER = os.environ.get('GEOCODING_PROVIDER', 'nominatim').lower()
NOMINATIM_BASE_URL = os.environ.get('NOMINATIM_BASE_URL', 'https://nominatim.openstreetmap.org').rstrip('/')
NOMINATIM_USER_AGENT = os.environ.get(
    'NOMINATIM_USER_AGENT',
    'FuelRouteApp-University-Assessment/1.0 (contact@fuelroute.local)'
)

HTTP_TIMEOUT_SECONDS = float(os.environ.get('HTTP_TIMEOUT_SECONDS', '10'))

ROUTE_CORRIDOR_MILES = float(os.environ.get('ROUTE_CORRIDOR_MILES', '25'))
MAX_RANGE_MILES = float(os.environ.get('MAX_RANGE_MILES', '500'))
MPG = float(os.environ.get('MPG', '10'))
STARTING_TANK = os.environ.get('STARTING_TANK', 'full').lower()

# Map Visualization Configuration (OpenFreeMap Liberty vector style, no API key required)
MAP_STYLE_URL = os.environ.get(
    'MAP_STYLE_URL',
    'https://tiles.openfreemap.org/styles/liberty'
)

FUEL_DATA_PATH = Path(os.environ.get('FUEL_DATA_PATH', str(BASE_DIR / 'data' / 'enriched_fuel_stations.json')))
RAW_FUEL_CSV_PATH = Path(os.environ.get('RAW_FUEL_CSV_PATH', str(BASE_DIR / 'data' / 'fuel-prices-for-be-assessment.csv')))
US_CITIES_CSV_PATH = Path(os.environ.get('US_CITIES_CSV_PATH', str(BASE_DIR / 'data' / 'us_cities.csv')))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'routes': {
            'handlers': ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': False,
        },
    },
}
