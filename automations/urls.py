# urls.py
from django.urls import path
from .views import ExecuteAITradeView, CloseAIPositionView # Import CloseAIPositionView

urlpatterns = [
    path('trade/execute/', ExecuteAITradeView.as_view(), name='ai_trade_execute'),
    path('close-position/<uuid:trade_id>/', CloseAIPositionView.as_view(), name='ai_close_position'),
]
