# accounts/services.py
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account, CTraderAccount
from mt5.services import MT5Connector
from connectors.ctrader_client import CTraderClient
from asgiref.sync import async_to_sync
from django.conf import settings
import requests

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
        try:
            ctrader_account = CTraderAccount.objects.get(account=account)
        except CTraderAccount.DoesNotExist:
            return {"error": "No linked cTrader account found."}
    
        payload = {
            "access_token": ctrader_account.access_token,
            "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
        }
        base_url = settings.CTRADER_API_BASE_URL  # e.g., "http://localhost:8080"
        
        # Call the new equity endpoint
        equity_url = f"{base_url}/ctrader/account/equity"
        try:
            equity_resp = requests.post(equity_url, json=payload, timeout=10)
        except requests.RequestException as e:
            return {"error": f"Error calling cTrader equity endpoint: {str(e)}"}
    
        if equity_resp.status_code != 200:
            return {"error": f"cTrader equity endpoint returned status: {equity_resp.status_code}"}
    
        equity_data = equity_resp.json()
        if "error" in equity_data:
            return {"error": equity_data["error"]}
    
        # Optionally, if you still need open_positions you can add another request here.
        # For this version, we simply return the equity information.
        return {
            "balance": equity_data.get("balance"),
            "equity": equity_data.get("equity"),
            "total_unrealized_pnl": equity_data.get("total_unrealized_pnl"),
        }
    
    else:
        return {"error": "Unsupported trading platform."}
