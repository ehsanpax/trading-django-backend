import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from utils.concurrency import get_redis_client

# Simple Redis-backed cache with in-process fallback
_mem: Dict[str, Dict[str, Any]] = {}
_redis = None
try:
    _redis = get_redis_client()
except Exception:
    _redis = None


def _price_key(account_id: str, symbol: str) -> str:
    return f"md:rc:price:{account_id}:{(symbol or '').upper()}"


def _symbol_key(account_id: str, symbol: str) -> str:
    return f"md:rc:symbol:{account_id}:{(symbol or '').upper()}"


def _now_s() -> int:
    return int(time.time())


def set_last_tick(
    account_id: str,
    symbol: str,
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
    last: Optional[float] = None,
    timestamp: Optional[Any] = None,
    ttl_seconds: int = 60,
) -> None:
    if not account_id or not symbol:
        return
    # Normalize timestamp to both ISO and epoch seconds
    epoch_s: Optional[int] = None
    iso: Optional[str] = None
    if isinstance(timestamp, (int, float)):
        epoch_s = int(timestamp if timestamp > 2_000_000_000 else timestamp)
        if epoch_s > 2_000_000_000:  # epoch ms
            epoch_s = int(epoch_s / 1000)
        try:
            iso = datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat()
        except Exception:
            iso = None
    elif isinstance(timestamp, str):
        try:
            # Accept 'Z' suffix too
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            iso = dt.astimezone(timezone.utc).isoformat()
            epoch_s = int(dt.timestamp())
        except Exception:
            iso = timestamp
            epoch_s = _now_s()
    elif timestamp is not None:
        try:
            dt = datetime.fromisoformat(str(timestamp))
            iso = dt.astimezone(timezone.utc).isoformat()
            epoch_s = int(dt.timestamp())
        except Exception:
            epoch_s = _now_s()
            iso = datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat()
    else:
        epoch_s = _now_s()
        iso = datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat()

    data = {
        'symbol': symbol,
        'bid': bid,
        'ask': ask,
        'last': last,
        'time': epoch_s,
        'timestamp': iso,
    }
    key = _price_key(str(account_id), symbol)
    _mem[key] = {'data': data, 'exp': _now_s() + ttl_seconds}
    if _redis:
        try:
            _redis.setex(key, ttl_seconds, json.dumps(data))
        except Exception:
            pass


def get_last_tick(account_id: str, symbol: str, *, max_age_seconds: int = 5) -> Optional[Dict[str, Any]]:
    if not account_id or not symbol:
        return None
    key = _price_key(str(account_id), symbol)
    now = _now_s()
    # Try Redis first
    if _redis:
        try:
            raw = _redis.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                except Exception:
                    data = None
                if isinstance(data, dict):
                    t = data.get('time')
                    if isinstance(t, (int, float)) and (now - int(t)) <= max_age_seconds:
                        return data
        except Exception:
            pass
    # Fallback to process-local
    item = _mem.get(key)
    if item and item.get('data'):
        data = item['data']
        t = data.get('time')
        if isinstance(t, (int, float)) and (now - int(t)) <= max_age_seconds and item.get('exp', 0) >= now:
            return data
    return None


def set_symbol_info(
    account_id: str,
    symbol: str,
    info: Dict[str, Any],
    *,
    ttl_seconds: int = 6 * 60 * 60,  # 6 hours
) -> None:
    if not account_id or not symbol or not isinstance(info, dict):
        return
    key = _symbol_key(str(account_id), symbol)
    payload = {'data': info, 'exp': _now_s() + ttl_seconds}
    _mem[key] = payload
    if _redis:
        try:
            _redis.setex(key, ttl_seconds, json.dumps(info))
        except Exception:
            pass


def get_symbol_info(account_id: str, symbol: str) -> Optional[Dict[str, Any]]:
    if not account_id or not symbol:
        return None
    key = _symbol_key(str(account_id), symbol)
    now = _now_s()
    if _redis:
        try:
            raw = _redis.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
        except Exception:
            pass
    item = _mem.get(key)
    if item and item.get('data') and item.get('exp', 0) >= now:
        return item['data']
    return None
