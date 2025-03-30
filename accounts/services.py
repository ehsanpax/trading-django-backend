# accounts/services.py
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account
from mt5.services import MT5Connector

def get_account_details(account_id, user):
    """
    Retrieves account details for the given account_id and user.
    For MT5 accounts, it logs in, retrieves account info and open positions.
    """
    account = get_object_or_404(Account, id=account_id, user=user)
    
    if account.platform == "MT5":
        try:
            mt5_account = MT5Account.objects.get(account=account)
        except MT5Account.DoesNotExist:
            return {"error": "No linked MT5 account found."}
        
        connector = MT5Connector(mt5_account.account_number, mt5_account.broker_server)
        login_result = connector.connect(mt5_account.encrypted_password)
        if "error" in login_result:
            return {"error": login_result["error"]}
        
        account_info = connector.get_account_info()
        positions = connector.get_open_positions()
        
        if "error" in account_info:
            return {"error": account_info["error"]}
        if "error" in positions:
            return {"error": positions["error"]}
        
        return {
            "balance": account_info.get("balance"),
            "equity": account_info.get("equity"),
            "margin": account_info.get("margin"),
            "open_positions": positions.get("open_positions")
        }
    elif account.platform == "cTrader":
        # Add cTrader logic here if implemented.
        return {"error": "cTrader support not implemented yet."}
    else:
        return {"error": "Unsupported trading platform."}
