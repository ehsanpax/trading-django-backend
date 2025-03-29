# trading_platform/asgi.py
import os
import django
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_platform.settings')

application = get_asgi_application()


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_platform.settings')

import price.routing  # your price app’s routing, for example
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            price.routing.websocket_urlpatterns
        )
    ),
})