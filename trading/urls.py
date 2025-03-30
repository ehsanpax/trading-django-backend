from django.urls import path
from .views import AccountListCreateView, AccountDetailView

urlpatterns = [
    path('accounts/', AccountListCreateView.as_view(), name='account-list-create'),
    path('accounts/<uuid:id>/', AccountDetailView.as_view(), name='account-detail'),
]
