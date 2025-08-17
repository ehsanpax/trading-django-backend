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
    def __init__(self, message: str, payload: Any | None = None):
        super().__init__(message)
        self.payload = payload


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
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": request_id,
    }
    if getattr(settings, "AI_STRATEGY_SEND_AUTH_HEADER", False):
        api_key = getattr(settings, 'AI_STRATEGY_API_KEY', '')
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _normalize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure strategy_name
    cfg.setdefault("strategy_name", "SECTIONED_SPEC")
    # Ensure indicator_configs present
    cfg.setdefault("indicator_configs", [])
    # Ensure strategy_params and sectioned_spec
    sp = cfg.setdefault("strategy_params", {})
    ss = sp.setdefault("sectioned_spec", {})
    # Move/copy strategy_graph into sectioned_spec
    if "strategy_graph" in cfg and "strategy_graph" not in ss:
        ss["strategy_graph"] = cfg["strategy_graph"]
    # Carry risk/filters into sectioned_spec for engine/task usage
    for k in ("risk", "filters"):
        if k in cfg and k not in ss:
            ss[k] = cfg[k]
        # Also keep top-level in strategy_params for compatibility if tasks read there
        if k in cfg and k not in sp:
            sp[k] = cfg[k]
    return cfg


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

    # Mask sensitive fields for logs
    safe_payload = dict(payload)
    if 'trading_account_api_key' in safe_payload and safe_payload['trading_account_api_key']:
        safe_payload['trading_account_api_key'] = f"***{str(safe_payload['trading_account_api_key'])[-4:]}"
    safe_headers = {k: ("***" if k.lower() == "authorization" else v) for k, v in headers.items()}

    logger.info(f"[AI] request_id={request_id} POST {url} timeout={timeout}s")
    logger.debug(f"[AI] headers={safe_headers} payload_keys={list(safe_payload.keys())} session_id={safe_payload.get('session_id')}")

    start = time.time()
    with httpx.Client(timeout=timeout) as client:
        resp = _breaker.call(client.post, url, headers=headers, json=payload)
    duration_ms = int((time.time() - start) * 1000)

    status = resp.status_code
    body_snippet = (resp.text or "")[:1000]
    logger.info(f"[AI] request_id={request_id} status={status} duration_ms={duration_ms}")

    if status == 200:
        try:
            data = resp.json()
        except Exception as e:
            logger.warning(f"[AI] request_id={request_id} invalid JSON: {e}; body_snippet={body_snippet}")
            raise ProviderError(f"Invalid JSON from provider: {e}")
        return data
    elif status in (400, 422):
        try:
            data = resp.json()
        except ValueError:
            logger.warning(f"[AI] request_id={request_id} validation non-JSON body: {body_snippet}")
            raise ValidationError(resp.text or "provider_validation_error")
        logger.warning(f"[AI] request_id={request_id} validation error payload={json.dumps(data)[:1000]}")
        raise ValidationError("provider_validation_error", payload=data)
    elif status in (401, 403):
        logger.warning(f"[AI] request_id={request_id} auth failed status={status} body={body_snippet}")
        raise ProviderError("Provider auth failed")
    elif status in (500, 502, 503, 504):
        logger.error(f"[AI] request_id={request_id} upstream error status={status} body={body_snippet}")
        raise ProviderError(f"Upstream error {status}")
    else:
        logger.error(f"[AI] request_id={request_id} unexpected status={status} body={body_snippet}")
        raise ProviderError(f"Unexpected status {status}")


def generate_strategy_config(
    *,
    bot_version: str | int,
    prompt: str,
    user_id: int | str,
    idempotency_key: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
    user_token: Optional[str] = None,
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

    # Build new provider payload (no auth header required)
    session_id = (options or {}).get('session_id') or request_id
    payload = {
        "chatInput": prompt,
        "session_id": session_id,
        "trading_account_api_key": user_token or "",
        "backend_url": getattr(settings, "BACKEND_URL", ""),
    }

    logger.info(
        f"[AI] generate start request_id={request_id} bot_version={bot_version} user_id={user_id} "
        f"prompt_len={len(prompt)} idempotency={'yes' if idempotency_key else 'no'} session_id={session_id}"
    )

    start = time.time()
    try:
        provider_resp = _call_provider(payload, request_id)
    except ValidationError:
        raise
    except pybreaker.CircuitBreakerError:
        logger.error(f"[AI] circuit open request_id={request_id}")
        raise ProviderError("circuit_open")
    except httpx.ReadTimeout:
        logger.error(f"[AI] timeout request_id={request_id}")
        raise ProviderError("timeout")
    except Exception as e:
        logger.error(f"[AI] provider call failed request_id={request_id} err={e}")
        raise ProviderError(str(e))
    duration_ms = int((time.time() - start) * 1000)

    # Expect provider return structure; be permissive initially
    raw = provider_resp if isinstance(provider_resp, dict) else {}
    config = json.loads(raw["output"])
    if not isinstance(config, dict):
        config = raw if isinstance(raw, dict) else None
    if not isinstance(config, dict):
        logger.error(f"[AI] invalid response shape request_id={request_id} raw_snippet={json.dumps(raw)[:1000] if raw else 'None'}")
        raise ValidationError("Invalid provider response shape")

    config = _normalize_config(config)

    result = {
        "config": config,
        "meta": {
            "provider": raw.get("provider") if isinstance(raw, dict) else None,
            "model": raw.get("model") if isinstance(raw, dict) else None,
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

    logger.info(f"[AI] generate success request_id={request_id} duration_ms={duration_ms} cached=False")
    return result
