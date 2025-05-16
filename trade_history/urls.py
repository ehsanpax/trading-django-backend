from django.urls import path
from . import views

app_name = 'trade_history'

urlpatterns = [
    path('trades/<uuid:pk>/', views.TradeHistoryDetailView.as_view(), name='trade-history-detail'),
    path('accounts/<uuid:account_pk>/trades/', views.AccountTradeHistoryListView.as_view(), name='account-trades-history-list'),
]
