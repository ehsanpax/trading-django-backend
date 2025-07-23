from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import re_path
import bots.routing
import price.routing
from .token_auth import TokenAuthMiddlewareStack

application = ProtocolTypeRouter({
    "websocket": TokenAuthMiddlewareStack(
        URLRouter(
            bots.routing.websocket_urlpatterns +
            price.routing.websocket_urlpatterns
        )
    ),
})
