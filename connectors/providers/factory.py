from __future__ import annotations
from typing import Literal

from .base import TradingProvider
from .ctrader import CTraderProvider

try:
    # If you have an MT5 provider wrapper, import it; else keep placeholder
    from .mt5 import MT5Provider  # type: ignore
except Exception:  # pragma: no cover
    MT5Provider = None  # type: ignore


def get_provider(platform: Literal["MT5", "cTrader"], *args, **kwargs) -> TradingProvider:
    if platform == "cTrader":
        return CTraderProvider()
    if platform == "MT5" and MT5Provider:
        return MT5Provider()
    # Default to cTrader if unknown for now; adjust as needed
    return CTraderProvider()
