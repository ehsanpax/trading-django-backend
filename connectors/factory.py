# connectors/factory.py
"""
Minimal connector factory for Phase 0.
Returns the same concrete clients previously used by TradeService
(MT5APIClient for MT5, CTraderClient for cTrader), preserving behavior.

Later phases can swap these with broker-agnostic connector implementations
without touching callers.
"""
from django.conf import settings
from django.shortcuts import get_object_or_404

from accounts.models import MT5Account, CTraderAccount, Account
from trading_platform.mt5_api_client import MT5APIClient
from connectors.ctrader_client import CTraderClient


def get_connector(account: Account):
    """
    Given an Account, return a platform-specific client instance matching
    the current code's expectations.
    """
    platform = (account.platform or "").strip()

    if platform.upper() == "MT5":
        mt5_acc = get_object_or_404(MT5Account, account=account)
        return MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_acc.account_number,
            password=mt5_acc.encrypted_password,
            broker_server=mt5_acc.broker_server,
            internal_account_id=str(account.id),
        )

    # Support both "cTrader" and "CTRADER" spellings
    if platform.lower() == "ctrader" or platform == "cTrader":
        ct_acc = get_object_or_404(CTraderAccount, account=account)
        return CTraderClient(ct_acc)

    raise RuntimeError(f"Unsupported platform: {platform}")
