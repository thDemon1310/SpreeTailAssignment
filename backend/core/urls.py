from django.urls import path
from .views import (
    RegisterView,
    MeView,
    GroupListCreateView,
    GroupDetailView,
    add_member,
    update_or_remove_member,
)

urlpatterns = [
    # Auth
    path('register/', RegisterView.as_view(), name='register'),
    path('me/', MeView.as_view(), name='me'),
]

# Group URLs — mounted at /api/groups/ in api_urls.py
group_urlpatterns = [
    path('', GroupListCreateView.as_view(), name='group-list-create'),
    path('<int:pk>/', GroupDetailView.as_view(), name='group-detail'),
    path('<int:group_id>/members/', add_member, name='group-add-member'),
    path('<int:group_id>/members/<int:membership_id>/', update_or_remove_member, name='group-update-member'),
]
