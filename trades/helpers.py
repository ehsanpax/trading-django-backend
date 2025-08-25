# common/helpers.py

import logging
from accounts.models import Account
from trading_platform.mt5_api_client import MT5APIClient
from django.shortcuts import get_object_or_404
from django.conf import settings
# New: platform-agnostic trading facade
from connectors.trading_service import TradingService

logger = logging.getLogger(__name__)


def fetch_symbol_info_for_platform(account, symbol: str) -> dict:
    """
    Fetch symbol info (pip size, lot size, etc.) via TradingService.
    Accepts an Account instance or account_id string.
    """
    if isinstance(account, str):
        account = get_object_or_404(Account, id=account)

    try:
        ts = TradingService(account)
        info = ts.get_symbol_info_sync(symbol)
        return info
    except Exception as e:
        logger.error(f"TradingService.get_symbol_info failed: {e}", exc_info=True)
        return {"error": f"Internal error fetching symbol info: {e}"}


def fetch_live_price_for_platform(account, symbol: str) -> dict:
    """
    Fetches the real-time bid/ask price for a given symbol, based on the account's platform.
    If a string is passed instead of an Account instance, it fetches the Account.
    Uses TradingService for platform-agnostic access (avoids localhost WebSocket coupling).
    """
    if isinstance(account, str):
        account = get_object_or_404(Account, id=account)

    try:
        ts = TradingService(account)
        price = ts.get_live_price_sync(symbol)
        # Normalize expected shape for downstream callers
        return {
            "symbol": price.get("symbol") or symbol,
            "bid": price.get("bid"),
            "ask": price.get("ask"),
            "timestamp": price.get("timestamp"),
        }
    except Exception as e:
        logger.error(f"TradingService.get_live_price_sync failed: {e}", exc_info=True)
        return {"error": f"Failed to fetch market price: {e}"}
