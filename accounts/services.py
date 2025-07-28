# accounts/services.py
from django.shortcuts import get_object_or_404
from accounts.models import Account, MT5Account, CTraderAccount
from trading_platform.mt5_api_client import connection_manager
from connectors.ctrader_client import CTraderClient
from asgiref.sync import async_to_sync
from django.conf import settings
import requests
import asyncio
import logging

logger = logging.getLogger(__name__)

async def get_account_details_async(account_id, user):
    """
    Asynchronously retrieves account details for the given account_id and user.
    This is the core async function.
    """
    account = await Account.objects.aget(id=account_id, user=user)
    
    if account.platform == "MT5":
        try:
            mt5_account = await MT5Account.objects.aget(account=account)
        except MT5Account.DoesNotExist:
            return {"error": "No linked MT5 account found."}

        client = await connection_manager.get_client(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_account.account_number,
            password=mt5_account.encrypted_password,
            broker_server=mt5_account.broker_server,
            internal_account_id=str(account.id)
        )
        
        # Wait for the initial data to be received from the WebSocket, with a timeout.
        logger.info(f"Service for account {account_id}: Waiting for initial data from MT5APIClient...")
        try:
            await asyncio.wait_for(client.initial_data_received.wait(), timeout=10.0)
            logger.info(f"Service for account {account_id}: Initial data received. Proceeding.")
        except asyncio.TimeoutError:
            logger.warning(f"Service for account {account_id}: Timed out waiting for initial data. Proceeding with cached data if available.")
        
        account_info = client.get_account_info()
        positions_data = client.get_open_positions()
        
        return {
            "balance": account_info.get("balance"),
            "equity": account_info.get("equity"),
            "margin": account_info.get("margin"),
            "open_positions": positions_data.get("open_positions", [])
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

@async_to_sync
async def get_account_details(account_id, user):
    """
    Synchronously retrieves account details.
    This is a wrapper for compatibility with synchronous views.
    """
    return await get_account_details_async(account_id, user)
