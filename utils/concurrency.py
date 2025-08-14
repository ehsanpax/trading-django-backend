import uuid
import logging
from contextlib import AbstractContextManager
from typing import Optional
from django.conf import settings

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if redis is None:
        return None
    url = getattr(settings, "REDIS_URL", None) or getattr(settings, "CELERY_BROKER_URL", None)
    if not url or not str(url).startswith("redis://"):
        return None
    try:
        _redis_client = redis.Redis.from_url(url, decode_responses=True)
        # Try a ping to verify connectivity
        _redis_client.ping()
        return _redis_client
    except Exception as e:  # pragma: no cover
        logger.warning(f"Redis client init failed: {e}")
        _redis_client = None
        return None


def redis_available() -> bool:
    return get_redis_client() is not None


class RedisLock(AbstractContextManager):
    """Simple, safe Redis-based lock context manager using SET NX PX and token compare on release.

    Usage:
        with RedisLock(key, ttl_ms) as lock:
            if not lock.acquired:
                # handle miss
            ...
    """

    def __init__(self, key: str, ttl_ms: int = 4000):
        self.key = key
        self.ttl_ms = int(ttl_ms or 0)
        self.token = str(uuid.uuid4())
        self.acquired = False
        self._client = get_redis_client()

    def __enter__(self):
        if not self._client:
            # No Redis: pretend lock acquired so caller proceeds unchanged
            self.acquired = True
            return self
        try:
            ok = self._client.set(self.key, self.token, nx=True, px=self.ttl_ms)
            self.acquired = bool(ok)
        except Exception as e:  # pragma: no cover
            logger.warning(f"RedisLock acquire failed for {self.key}: {e}")
            self.acquired = False
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self._client:
            return False
        # Lua script to safely release lock if token matches
        lua = (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end"
        )
        try:
            self._client.eval(lua, 1, self.key, self.token)
        except Exception as e:  # pragma: no cover
            logger.warning(f"RedisLock release failed for {self.key}: {e}")
        return False


def is_in_cooldown(key: str) -> bool:
    """Return True if a cooldown key exists."""
    client = get_redis_client()
    if not client:
        return False
    try:
        return bool(client.exists(key))
    except Exception as e:  # pragma: no cover
        logger.warning(f"Cooldown check failed for {key}: {e}")
        return False


def mark_cooldown(key: str, cooldown_seconds: int) -> None:
    client = get_redis_client()
    if not client:
        return
    try:
        client.set(key, "1", ex=int(cooldown_seconds))
    except Exception as e:  # pragma: no cover
        logger.warning(f"Cooldown mark failed for {key}: {e}")
