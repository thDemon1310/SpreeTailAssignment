"""
API URL configuration — all endpoints under /api/.
"""

from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from core.urls import group_urlpatterns

urlpatterns = [
    # JWT auth
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Auth (register, me)
    path('auth/', include('core.urls')),

    # Groups
    path('groups/', include(group_urlpatterns)),
]
