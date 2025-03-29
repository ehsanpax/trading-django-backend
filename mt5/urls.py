# mt5/urls.py
from django.urls import path
from .views import (
    ConnectMT5View,
    MT5TradeView,
    MT5PositionView,
    MT5SymbolInfoView,
    MT5MarketPriceView,
)

urlpatterns = [
    path('connect/', ConnectMT5View.as_view(), name='mt5-connect'),
    path('trade/', MT5TradeView.as_view(), name='mt5-trade'),
    path('position/', MT5PositionView.as_view(), name='mt5-position'),
    path('symbol-info/<str:account_id>/<str:symbol>/', MT5SymbolInfoView.as_view(), name='mt5-symbol-info'),
    path('market-price/<str:symbol>/<str:account_id>/', MT5MarketPriceView.as_view(), name='mt5-market-price'),
]
