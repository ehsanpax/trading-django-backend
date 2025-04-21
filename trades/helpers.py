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
    #print("DETECTED TRADING PLATFORM:" , platform)
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
        
        import requests
        from django.conf import settings

        payload = {
            "access_token": ctrader_account.access_token,
            "ctid_trader_account_id": ctrader_account.ctid_trader_account_id,
            "symbol": symbol.upper()
        }
        base_url = settings.CTRADER_API_BASE_URL  # e.g. "http://localhost:8080"
        symbol_info_url = f"{base_url}/ctrader/symbol/info"
        
        try:
            response = requests.post(symbol_info_url, json=payload, timeout=10)
        except requests.RequestException as e:
            return {"error": f"Error calling cTrader symbol info endpoint: {str(e)}"}
        
        if response.status_code != 200:
            return {"error": f"cTrader symbol info endpoint returned status: {response.status_code}"}
        
        data = response.json()
        if "error" in data:
            return {"error": data["error"]}
        
        # Retrieve the nested symbol info from data["symbol_info"]["symbol"]
        symbol_info_container = data.get("symbol_info", {})
        symbol_field = symbol_info_container.get("symbol")
        if not symbol_field:
            return {"error": "Invalid symbol info received from cTrader API.",
                    "returned_keys": list(data.keys())}
        
        if isinstance(symbol_field, list):
            if not symbol_field:
                return {"error": "Empty symbol info list received from cTrader API."}
            raw_info = symbol_field[0]
        elif isinstance(symbol_field, dict):
            raw_info = symbol_field
        else:
            return {"error": "Invalid symbol info received from cTrader API: unexpected type."}
        
        try:
            # Use pipPosition to calculate pip_size directly.
            pip_position = int(raw_info.get("pipPosition", 0))
            pip_size = 10 ** (-pip_position)
            
            # tick_size is still assumed to be 10^(-digits)
            digits = int(raw_info.get("digits", 0))
            tick_size = 10 ** (-digits) if digits else None
            
            lot_size = float(raw_info.get("lotSize", 0))/100
            swap_short = float(raw_info.get("swapShort", 0))
            swap_long = float(raw_info.get("swapLong", 0))
        except (ValueError, TypeError):
            return {"error": "Invalid numeric value in symbol info from cTrader API."}
        
        # Assume a default contract size (e.g. 100000 for FX instruments)
        contract_size = 100000.0
        
        expected_info = {
            "symbol": raw_info.get("symbol", symbol.upper()),
            "pip_size": pip_size,
            "tick_size": tick_size,
            "contract_size": lot_size,
            "lot_size": lot_size,
            "swap_short": swap_short,
            "swap_long": swap_long,
        }
        return expected_info
    else:
        return {"error": f"Unsupported trading platform!!!: {account.platform}"}


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
        try:
            import websocket
            import json
            import time

            # Connect to the WebSocket server with a timeout of 5 seconds.
            ws = websocket.create_connection("ws://localhost:9000", timeout=5)

            # Wait for the server’s greeting message
            greeting = ws.recv()
            greeting_data = json.loads(greeting)
            if greeting_data.get("status") != "connected":
                ws.close()
                return {"error": "Failed to connect to cTrader live price server."}

            # Now, wait for the price event matching the requested symbol.
            # We loop for up to 5 seconds to receive a price update.
            start_time = time.time()
            timeout_duration = 5  # seconds
            price_event = None
            while time.time() - start_time < timeout_duration:
                try:
                    message = ws.recv()
                    data = json.loads(message)
                    # Check if this update is for our requested symbol (case-insensitive)
                    if data.get("symbol", "").upper() == symbol.upper():
                        price_event = data
                        break
                except Exception:
                    # If reading a message fails, break out of the loop.
                    break
            ws.close()
            if not price_event:
                return {"error": "Did not receive price update for symbol within timeout."}

            return {"symbol": symbol.upper(), "bid": price_event.get("bid"), "ask": price_event.get("ask")}

        except Exception as e:
            return {"error": "Error connecting to cTrader WebSocket: " + str(e)}
    else:
        return {"error": f"Unsupported trading platform: {account.platform}"}
