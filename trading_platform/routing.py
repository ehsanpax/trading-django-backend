from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from django.urls import re_path
from accounts.consumers import AccountConsumer
from bots.consumers import BacktestConsumer
from price.consumers import PriceConsumer
from monitoring.routing import websocket_urlpatterns as monitoring_ws_urlpatterns
from .token_auth import TokenAuthMiddlewareStack

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": TokenAuthMiddlewareStack(
        URLRouter([
            # Accounts
            re_path(r'^ws/accounts/(?P<account_id>[0-9a-f-]+)/$', AccountConsumer.as_asgi()),
            # Bots
            re_path(r'^ws/backtest/(?P<backtest_run_id>[0-9a-f-]+)/$', BacktestConsumer.as_asgi()),
            # Prices
            re_path(r'^ws/prices/(?P<account_id>[^/]*)/(?P<symbol>[^/]+)/?$', PriceConsumer.as_asgi()),
        ] + monitoring_ws_urlpatterns)
    ),
})
