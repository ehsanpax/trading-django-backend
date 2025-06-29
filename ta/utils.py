# File: ta/utils.py  (placeholders – plug your own data APIs)
# ────────────────────────────────
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import pandas as pd


def fetch_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame:
    """Return OHLCV DataFrame with 'close_ts' tz‑aware; implement via MT5/cTrader/etc."""
    raise NotImplementedError


def save_chart_snapshot(symbol: str, timeframe: str, ohlcv: pd.DataFrame) -> str | None:
    """Generate & save a 3‑panel collage, return storage URL/path. Stub here."""
    return None


def calc_ttl(timeframe: str):
    mapping = {"15m": 7, "1H": 30, "4H": 90, "D": 365}
    days = mapping.get(timeframe, 30)
    return datetime.now(timezone.utc) + timedelta(days=days)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
