from django.urls import path
from . import views

app_name = 'trade_history'

urlpatterns = [
    path('trades/<uuid:pk>/', views.TradeHistoryDetailView.as_view(), name='trade-history-detail'),
]
