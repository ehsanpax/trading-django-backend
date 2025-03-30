# common/helpers.py

from accounts.models import Account, MT5Account, CTraderAccount
from mt5.services import MT5Connector
from django.shortcuts import get_object_or_404

def fetch_symbol_info_for_platform(account, symbol: str) -> dict:
    """
    Fetches pip size, contract size, etc. for the given symbol,
    depending on the account's platform type.
    If 'account' is a string (i.e. an account_id), fetch the Account instance.
    """
    if isinstance(account, str):
        account = get_object_or_404(Account, id=account)
    
    platform = account.platform.upper()
    
    if platform == "MT5":
        mt5_account = getattr(account, "mt5_account", None)
        if not mt5_account:
            return {"error": "No linked MT5 account found."}

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return {"error": login_result["error"]}

        symbol_info = connector.get_symbol_info(symbol)
        return symbol_info  # Might return {"error": "..."} if the symbol is invalid

    elif platform == "CTRADER":
        ctrader_account = getattr(account, "ctrader_account", None)
        if not ctrader_account:
            return {"error": "No linked cTrader account found."}
        # Implement cTrader connector logic here.
        return {"error": "cTrader logic not implemented yet"}
    else:
        return {"error": f"Unsupported trading platform: {account.platform}"}


def fetch_live_price_for_platform(account, symbol: str) -> dict:
    """
    Fetches the real-time bid/ask price for a given symbol, based on the account's platform.
    If a string is passed instead of an Account instance, it fetches the Account.
    """
    if isinstance(account, str):
        account = get_object_or_404(Account, id=account)
    
    platform = account.platform.upper()

    if platform == "MT5":
        mt5_account = getattr(account, "mt5_account", None)
        if not mt5_account:
            return {"error": "No linked MT5 account found."}

        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return {"error": login_result["error"]}

        price_data = connector.get_live_price(symbol)
        return price_data  # Expected to be {"bid": ..., "ask": ...} or an error dict

    elif platform == "CTRADER":
        ctrader_account = getattr(account, "ctrader_account", None)
        if not ctrader_account:
            return {"error": "No linked cTrader account found."}
        # Implement cTrader connector logic here.
        return {"error": "cTrader logic not implemented yet"}
    else:
        return {"error": f"Unsupported trading platform: {account.platform}"}
