# risk/urls.py
from django.urls import path
from .views import CalculateLotSizeView
from .views import RiskManagementDetailView

urlpatterns = [
    path('calculate_lot_size/', CalculateLotSizeView.as_view(), name='calculate-lot-size'),
    path('settings/', RiskManagementDetailView.as_view(), name='risk-settings'),
]
