# urls.py
from django.urls import path
from .views import ExecuteAITradeView

urlpatterns = [
    path('trade/execute/', ExecuteAITradeView.as_view(), name='ai_trade_execute'),
]
