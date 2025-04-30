# trades/urls.py
from django.urls import path
from .views import (
    ExecuteTradeView, OpenTradesView, UpdateTradeView,
    CloseTradeView, TradeSymbolInfoView, MarketPriceView, OpenPositionsLiveView, PendingOrdersView, AllOpenPositionsLiveView, AllPendingOrdersView
)

urlpatterns = [
    path('execute/', ExecuteTradeView.as_view(), name='execute-trade'),
    path('open/', OpenTradesView.as_view(), name='open-trades'),
    path('update/<str:trade_id>/', UpdateTradeView.as_view(), name='update-trade'),
    path('close/<str:trade_id>/', CloseTradeView.as_view(), name='close-trade'),
    path('symbol-info/<str:account_id>/<str:symbol>/', TradeSymbolInfoView.as_view(), name='trade-symbol-info'),
    path('market-price/<str:account_id>/<str:symbol>/', MarketPriceView.as_view(), name='market-price'),
    path('open-positions/<uuid:account_id>/', OpenPositionsLiveView.as_view(), name="open_positions_live"),
    path('pending-orders/<uuid:account_id>//', PendingOrdersView.as_view(),name='pending-orders'),
    path('all-open-positions/', AllOpenPositionsLiveView.as_view(), name="all_open_positions_live"),
    path('all-pending-orders/', AllPendingOrdersView.as_view(), name="all_pending_orders")
]
