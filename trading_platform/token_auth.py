import logging
from channels.auth import AuthMiddlewareStack
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from urllib.parse import parse_qs

User = get_user_model()
logger = logging.getLogger(__name__)

@database_sync_to_async
def get_user(token_key):
    try:
        token = AccessToken(token_key)
        user_id = token.payload.get('user_id')
        return User.objects.get(id=user_id)
    except Exception:
        return AnonymousUser()

class TokenAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        logger.info(f"WebSocket connection attempt with path: {scope.get('path')}")
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string or "")
        token_values = params.get("token", [])
        if token_values:
            token_key = token_values[0]
            user = await get_user(token_key)
            scope["user"] = user
            try:
                uid = getattr(user, 'id', None)
                logger.info(f"WS auth resolved user_id={uid} path={scope.get('path')}")
            except Exception:
                pass
        else:
            scope["user"] = AnonymousUser()
            logger.info(f"WS auth missing token, using AnonymousUser path={scope.get('path')}")
        return await self.inner(scope, receive, send)

def TokenAuthMiddlewareStack(inner):
    return TokenAuthMiddleware(AuthMiddlewareStack(inner))
