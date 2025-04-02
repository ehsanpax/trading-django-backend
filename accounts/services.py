# accounts/services.py
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account
from mt5.services import MT5Connector
from service.service_adapter import ServiceAdapter

def get_account_details(account_id, user):
    account = get_object_or_404(Account, id=account_id, user=user)

    service_adapter = ServiceAdapter(account=account, service_type=account.platform)
    login_result = service_adapter.connect()
    if login_result.message_type == "error":
        return {"error": login_result.message}
    
    account_info = service_adapter.get_account_info()
    positions = service_adapter.get_open_positions()
    if account_info.message_type == "error":
        return {"error": account_info.message}
    if positions.message_type == "error":
        return {"error": positions.message}
    
    return {
        "balance": account_info.get("balance"),
        "equity": account_info.get("equity"),
        "margin": account_info.get("margin"),
        "open_positions": positions.get("open_positions")
    }

