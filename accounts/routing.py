from django.urls import re_path
from .consumers import AccountConsumer

websocket_urlpatterns = [
    re_path(r"^(?P<account_id>[0-9a-f-]+)/?$", AccountConsumer.as_asgi()),
]
