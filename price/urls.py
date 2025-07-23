from django.urls import path
from . import views

urlpatterns = [
    path('chart/history/', views.get_historical_candles, name='get_historical_candles'),
]
