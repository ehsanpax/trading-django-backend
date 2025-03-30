# price/routing.py
from django.urls import re_path
from .consumers import PriceConsumer

websocket_urlpatterns = [
    re_path(r'^ws/prices/(?P<account_id>[^/]+)/(?P<symbol>[^/]+)/?$', PriceConsumer.as_asgi())
]
