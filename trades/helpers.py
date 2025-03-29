# common/helpers.py

from accounts.models import Account, MT5Account, CTraderAccount
from mt5.services import MT5Connector
from django.shortcuts import get_object_or_404

# from connectors.ctrader_connector import CTraderConnector  # Example if you have a cTrader connector

def fetch_symbol_info_for_platform(account: Account, symbol: str) -> dict:
    """
    Fetches pip size, contract size, etc. for the given symbol,
    depending on the account's platform type.
    """
    platform = account.platform.upper()
    
    if platform == "MT5":
        # 1️⃣ Grab the MT5 account
        mt5_account = getattr(account, "mt5_account", None)
        if not mt5_account:
            return {"error": "No linked MT5 account found."}

        # 2️⃣ Instantiate the MT5 connector
        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return {"error": login_result["error"]}

        # 3️⃣ Fetch symbol info
        symbol_info = connector.get_symbol_info(symbol)
        return symbol_info  # Might be {"error": "..."} if the symbol is invalid

    elif platform == "CTRADER":
        # 1️⃣ Grab the cTrader account
        ctrader_account = getattr(account, "ctrader_account", None)
        if not ctrader_account:
            return {"error": "No linked cTrader account found."}

        # 2️⃣ Instantiate cTrader connector
        # connector = CTraderConnector(is_live=ctrader_account.live, access_token=ctrader_account.access_token)
        # 3️⃣ Fetch symbol info (assuming you have a get_symbol_info method)
        # symbol_info = connector.get_symbol_info(symbol)
        return {"error": "cTrader logic not implemented yet"}

    else:
        return {"error": f"Unsupported trading platform: {account.platform}"}
def fetch_live_price_for_platform(account: Account, symbol: str) -> dict:
    """
    Fetches the real-time bid/ask price for a given symbol, based on the account's platform.
    """
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
        return price_data  # e.g. {"bid": ..., "ask": ...} or {"error": ...}

    elif platform == "CTRADER":
        ctrader_account = getattr(account, "ctrader_account", None)
        if not ctrader_account:
            return {"error": "No linked cTrader account found."}

        # connector = CTraderConnector(is_live=ctrader_account.live, access_token=ctrader_account.access_token)
        # price_data = connector.get_live_price(symbol)
        return {"error": "cTrader logic not implemented yet"}

    else:
        return {"error": f"Unsupported trading platform: {account.platform}"}