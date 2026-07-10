"""
URL configuration for spreetail_backend project.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('spreetail_backend.api_urls')),
]
