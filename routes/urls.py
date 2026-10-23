"""
Routes URL patterns.
"""
from django.urls import path
from routes.views import RouteOptimizeView

urlpatterns = [
    path('optimize/', RouteOptimizeView.as_view(), name='route-optimize'),
]
