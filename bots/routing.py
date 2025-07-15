from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/backtest/(?P<backtest_run_id>[0-9a-f-]+)/$', consumers.BacktestConsumer.as_asgi()),
]
