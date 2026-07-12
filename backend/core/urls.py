from django.urls import path
from .views import (
    RegisterView,
    MeView,
    GroupListCreateView,
    GroupDetailView,
    add_member,
    update_or_remove_member,
    expense_list_create,
    expense_detail,
    group_balances,
    group_user_balance_detail,
    settlement_list_create,
    import_csv,
    import_anomalies,
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
    # Expense endpoints nested under groups
    path('<int:group_id>/expenses/', expense_list_create, name='group-expense-list-create'),
    path('<int:group_id>/expenses/<int:expense_id>/', expense_detail, name='group-expense-detail'),
    # Settlements
    path('<int:group_id>/settlements/', settlement_list_create, name='group-settlement-list-create'),
    # Balances
    path('<int:group_id>/balances/', group_balances, name='group-balances'),
    path('<int:group_id>/balances/<int:user_id>/', group_user_balance_detail, name='group-user-balance'),
    # Import
    path('<int:group_id>/import/', import_csv, name='group-import'),
    path('<int:group_id>/import/<int:batch_id>/anomalies/', import_anomalies, name='group-import-anomalies'),
]
