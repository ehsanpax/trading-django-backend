from django.urls import path
from . import views

urlpatterns = [
    path('chart/history/', views.CandleViewset.as_view(), name='get_historical_candles'),
    path('chart/data/', views.ChartViewset.as_view(), name='get_chart_data'),
]
