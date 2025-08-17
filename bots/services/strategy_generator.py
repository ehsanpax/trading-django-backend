import json
import logging
import time
import uuid
import hashlib
from typing import Any, Dict, Optional

import httpx
from django.conf import settings
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type
import pybreaker

from utils.concurrency import get_redis_client

logger = logging.getLogger("bots")

# Circuit breaker for provider calls
_breaker = pybreaker.CircuitBreaker(
    fail_max=getattr(settings, "AI_STRATEGY_CIRCUIT_FAIL_MAX", 5),
    reset_timeout=getattr(settings, "AI_STRATEGY_CIRCUIT_RESET_SEC", 60),
    name="ai_strategy_provider",
)


class ProviderError(Exception):
    pass


class ValidationError(Exception):
    pass


def _hash_prompt(bot_version: str | int, prompt: str, options: Optional[dict]) -> str:
    h = hashlib.sha256()
    h.update(str(bot_version).encode())
    h.update(b"|")
    h.update(prompt.encode(errors="ignore"))
    h.update(b"|")
    if options:
        h.update(json.dumps(options, sort_keys=True).encode())
    return h.hexdigest()


def _build_headers(request_id: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {getattr(settings, 'AI_STRATEGY_API_KEY', '')}",
        "Content-Type": "application/json",
        "X-Request-ID": request_id,
    }


@retry(
    reraise=True,
    stop=stop_after_attempt(getattr(settings, "AI_STRATEGY_RETRY_MAX_ATTEMPTS", 2) + 1),
    wait=wait_exponential_jitter(initial=0.5, max=3.0),
    retry=retry_if_exception_type((httpx.HTTPError, ProviderError)),
)
def _call_provider(payload: Dict[str, Any], request_id: str) -> Dict[str, Any]:
    url = getattr(settings, "AI_STRATEGY_API_URL", "")
    if not url:
        raise ProviderError("AI provider URL not configured")
    timeout = getattr(settings, "AI_STRATEGY_TIMEOUT_SEC", 15)
    headers = _build_headers(request_id)

    with httpx.Client(timeout=timeout) as client:
        resp = _breaker.call(client.post, url, headers=headers, json=payload)
        status = resp.status_code
        if status == 200:
            try:
                data = resp.json()
            except Exception as e:
                raise ProviderError(f"Invalid JSON from provider: {e}")
            return data
        elif status in (400, 422):
            raise ValidationError(resp.text)
        elif status in (401, 403):
            raise ProviderError("Provider auth failed")
        elif status in (500, 502, 503, 504):
            raise ProviderError(f"Upstream error {status}")
        else:
            raise ProviderError(f"Unexpected status {status}")


def generate_strategy_config(
    *,
    bot_version: str | int,
    prompt: str,
    user_id: int | str,
    idempotency_key: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not prompt:
        raise ValidationError("prompt is required")

    max_len = getattr(settings, "AI_STRATEGY_MAX_PROMPT_CHARS", 4000)
    if len(prompt) > max_len:
        raise ValidationError(f"prompt too long (>{max_len} chars)")

    request_id = str(uuid.uuid4())
    prompt_hash = _hash_prompt(bot_version, prompt, options)

    # Cache and idempotency via Redis if available
    redis_client = get_redis_client()

    # Idempotency check
    if idempotency_key and redis_client:
        idem_key = f"bots:ai_strategy:idemp:{idempotency_key}"
        cached = redis_client.get(idem_key)
        if cached:
            try:
                data = json.loads(cached)
                data.setdefault("meta", {}).update({"cached": True, "request_id": request_id, "prompt_hash": prompt_hash})
                return data
            except Exception:
                pass

    # Content cache
    cache_key = f"bots:ai_strategy:cache:{prompt_hash}"
    if redis_client:
        cached = redis_client.get(cache_key)
        if cached:
            try:
                data = json.loads(cached)
                data.setdefault("meta", {}).update({"cached": True, "request_id": request_id, "prompt_hash": prompt_hash})
                return data
            except Exception:
                pass

    payload = {
        "bot_version": str(bot_version),
        "prompt": prompt,
        "options": options or {},
        "trace_id": request_id,
        "user_id": str(user_id),
    }

    start = time.time()
    try:
        provider_resp = _call_provider(payload, request_id)
    except ValidationError:
        raise
    except pybreaker.CircuitBreakerError:
        raise ProviderError("circuit_open")
    except httpx.ReadTimeout:
        raise ProviderError("timeout")
    except Exception as e:
        raise ProviderError(str(e))
    duration_ms = int((time.time() - start) * 1000)

    # Expect provider return structure; be permissive initially
    config = provider_resp.get("config") if isinstance(provider_resp, dict) else None
    if not isinstance(config, dict):
        # If provider returns raw config dict, wrap it
        if isinstance(provider_resp, dict):
            config = provider_resp
        else:
            raise ValidationError("Invalid provider response shape")

    result = {
        "config": config,
        "meta": {
            "provider": provider_resp.get("provider") if isinstance(provider_resp, dict) else None,
            "model": provider_resp.get("model") if isinstance(provider_resp, dict) else None,
            "request_id": request_id,
            "cached": False,
            "duration_ms": duration_ms,
            "prompt_hash": prompt_hash,
        },
    }

    # Save to cache and idempotency store
    if redis_client:
        ttl = int(getattr(settings, "AI_STRATEGY_CACHE_TTL_SEC", 600))
        try:
            redis_client.setex(cache_key, ttl, json.dumps(result))
            if idempotency_key:
                idem_key = f"bots:ai_strategy:idemp:{idempotency_key}"
                redis_client.setex(idem_key, ttl, json.dumps(result))
        except Exception:
            logger.warning("Failed to save AI strategy response to Redis cache")

    return result
