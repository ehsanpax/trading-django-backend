# risk/urls.py
from django.urls import path
from .views import CalculateLotSizeView

urlpatterns = [
    path('calculate_lot_size/', CalculateLotSizeView.as_view(), name='calculate-lot-size'),
]
