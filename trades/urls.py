# trades/urls.py
from django.urls import path
from .views import (
    ExecuteTradeView, OpenTradesView, UpdateTakeProfitView, # Changed UpdateTradeView to UpdateTakeProfitView
    CloseTradeView, TradeSymbolInfoView, MarketPriceView, OpenPositionsLiveView, PendingOrdersView, AllOpenPositionsLiveView, AllPendingOrdersView,
    UpdateStopLossAPIView, PartialCloseTradeView
)

urlpatterns = [
    path('execute/', ExecuteTradeView.as_view(), name='execute-trade'),
    path('open/', OpenTradesView.as_view(), name='open-trades'),
    path('update-tp/<str:trade_id_str>/', UpdateTakeProfitView.as_view(), name='update-trade-tp'), # Changed path and name
    path('close/<str:trade_id>/', CloseTradeView.as_view(), name='close-trade'), # Assuming trade_id here is fine, but changed to trade_id_str in UpdateTakeProfitView
    path('symbol-info/<str:account_id>/<str:symbol>/', TradeSymbolInfoView.as_view(), name='trade-symbol-info'),
    path('market-price/<str:account_id>/<str:symbol>/', MarketPriceView.as_view(), name='market-price'),
    path('open-positions/<uuid:account_id>/', OpenPositionsLiveView.as_view(), name="open_positions_live"),
    path('pending-orders/<uuid:account_id>/', PendingOrdersView.as_view(),name='pending-orders'), # Corrected double slash
    path('all-open-positions/', AllOpenPositionsLiveView.as_view(), name="all_open_positions_live"),
    path('all-pending-orders/', AllPendingOrdersView.as_view(), name="all_pending_orders"),
    path('update-sl/', UpdateStopLossAPIView.as_view(), name='update_trade_stop_loss'),
    path('<str:trade_id_str>/partial-close/', PartialCloseTradeView.as_view(), name='partial-close-trade'),
]
