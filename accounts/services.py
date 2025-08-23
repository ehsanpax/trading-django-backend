# accounts/services.py
from django.shortcuts import get_object_or_404
from accounts.models import Account, CTraderAccount
from connectors.factory import is_platform_supported
from django.conf import settings
import requests
import asyncio
import logging

logger = logging.getLogger(__name__)

# Adapter helpers to normalize TradingService DTOs or dicts

def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_account_fields(acc):
    return {
        "balance": _get(acc, "balance"),
        "equity": _get(acc, "equity"),
        "margin": _get(acc, "margin"),
    }


def _position_to_dict(p):
    return {
        "ticket": _get(p, "position_id") or _get(p, "ticket") or _get(p, "id"),
        "symbol": _get(p, "symbol"),
        "direction": _get(p, "direction") or _get(p, "side"),
        "volume": _get(p, "volume") or _get(p, "lots") or _get(p, "qty"),
        "open_price": _get(p, "open_price") or _get(p, "price_open") or _get(p, "entry_price"),
        "current_price": _get(p, "current_price") or _get(p, "price_current") or _get(p, "market_price"),
        "stop_loss": _get(p, "stop_loss") or _get(p, "sl"),
        "take_profit": _get(p, "take_profit") or _get(p, "tp"),
        "profit": _get(p, "profit") or _get(p, "unrealized_pnl") or _get(p, "pnl"),
        "swap": _get(p, "swap"),
        "commission": _get(p, "commission") or _get(p, "fees"),
    }

async def get_account_details_async(account_id, user):
    """
    Asynchronously retrieves account details for the given account_id and user.
    This is the core async function.
    """
    account = await Account.objects.aget(id=account_id, user=user)

    # Try TradingService only for supported platforms (avoid noisy errors for unsupported ones)
    platform = (account.platform or "").strip()
    if is_platform_supported(platform):
        try:
            from connectors.trading_service import TradingService
            ts = TradingService(account)
            acc = await ts.get_account_info()
            positions = await ts.get_open_positions()
            logger.info("accounts.details path=ts mode=async account_id=%s", account_id)
            return {
                **_extract_account_fields(acc),
                "open_positions": [_position_to_dict(p) for p in (positions or [])],
            }
        except Exception:
            logger.exception(
                "TradingService snapshot failed for account %s.",
                account_id,
            )

    # Temporary: retain cTrader fallback until connector is implemented
    if (account.platform or "").lower() == "ctrader":
        try:
            ctrader_account = CTraderAccount.objects.get(account=account)
        except CTraderAccount.DoesNotExist:
            return {"error": "No linked cTrader account found."}

        payload = {
            "access_token": ctrader_account.access_token,
            "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
        }
        base_url = settings.CTRADER_API_BASE_URL
        equity_url = f"{base_url.rstrip('/')}/ctrader/account_info"
        try:
            equity_resp = requests.post(equity_url, json=payload, timeout=10)
        except requests.RequestException as e:
            return {"error": f"Error calling cTrader equity endpoint: {str(e)}"}

        if equity_resp.status_code != 200:
            return {"error": f"cTrader equity endpoint returned status: {equity_resp.status_code}"}

        equity_data = equity_resp.json()
        if "error" in equity_data:
            return {"error": equity_data["error"]}

        logger.info("accounts.details path=legacy platform=cTrader mode=async account_id=%s", account_id)
        return {
            "balance": equity_data.get("balance"),
            "equity": equity_data.get("equity"),
            "total_unrealized_pnl": equity_data.get("total_unrealized_pnl"),
        }

    # No legacy fallbacks for MT5 anymore
    return {"error": "Account details unavailable via TradingService."}


def _get_account_details_via_rest(account_id, user):
    """Synchronous, event-loop-safe account details resolver using TradingService or cTrader fallback."""
    account = get_object_or_404(Account, id=account_id, user=user)

    # TradingService sync wrappers only if platform is supported
    platform = (account.platform or "").strip()
    if is_platform_supported(platform):
        try:
            from connectors.trading_service import TradingService
            ts = TradingService(account)
            acc = ts.get_account_info_sync()
            positions = ts.get_open_positions_sync()
            logger.info("accounts.details path=ts mode=sync account_id=%s", account_id)
            return {
                **_extract_account_fields(acc),
                "open_positions": [_position_to_dict(p) for p in (positions or [])],
            }
        except Exception:
            logger.exception(
                "TradingService sync snapshot failed for account %s.",
                account_id,
            )

    # Temporary: retain cTrader fallback until connector is implemented
    if (account.platform or "").lower() == "ctrader":
        try:
            ctrader_account = CTraderAccount.objects.get(account=account)
        except CTraderAccount.DoesNotExist:
            return {"error": "No linked cTrader account found."}

        payload = {
            "access_token": ctrader_account.access_token,
            "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
        }
        base_url = settings.CTRADER_API_BASE_URL
        equity_url = f"{base_url.rstrip('/')}/ctrader/account_info"
        try:
            equity_resp = requests.post(equity_url, json=payload, timeout=10)
            if equity_resp.status_code != 200:
                return {"error": f"cTrader equity endpoint returned status: {equity_resp.status_code}"}
            equity_data = equity_resp.json()
        except requests.RequestException as e:
            return {"error": f"Error calling cTrader equity endpoint: {str(e)}"}

        if "error" in equity_data:
            return {"error": equity_data["error"]}

        logger.info("accounts.details path=legacy platform=cTrader mode=sync account_id=%s", account_id)
        return {
            "balance": equity_data.get("balance"),
            "equity": equity_data.get("equity"),
            "total_unrealized_pnl": equity_data.get("total_unrealized_pnl"),
        }

    # No legacy fallbacks for MT5 anymore
    return {"error": "Account details unavailable via TradingService."}


def get_account_details(account_id, user):
    """
    Synchronous facade that is safe in threads with running event loops.
    Uses REST fallbacks to avoid AsyncToSync conflicts.
    """
    # Always use the REST-based resolver (internally tries TradingService sync wrappers
    # and falls back to legacy paths as needed). Avoid probing event loop to reduce noise.
    return _get_account_details_via_rest(account_id, user)
