"""
URL Configuration for FuelRoute API.
"""
from django.urls import path, include
from routes.views import HealthCheckView, LivenessCheckView, ReadinessCheckView, DemoView

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health-check'),
    path('health/live/', LivenessCheckView.as_view(), name='health-liveness'),
    path('health/ready/', ReadinessCheckView.as_view(), name='health-readiness'),
    path('demo/', DemoView.as_view(), name='demo-view'),
    path('api/v1/routes/', include('routes.urls')),
]
