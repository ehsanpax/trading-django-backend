import requests
from typing import Dict, Any, Optional

class MT5APIClient:
    def __init__(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str):
        self.base_url = base_url
        self.account_id = account_id
        self.password = password
        self.broker_server = broker_server
        self.internal_account_id = internal_account_id

    def _get_auth_payload(self) -> Dict[str, Any]:
        print("Using MT5 API client with account ID:", self.account_id)
        return {
            "account_id": self.account_id, # This is the MT5 account number
            "password": self.password,
            "broker_server": self.broker_server,
            "internal_account_id": self.internal_account_id, # This is the internal account ID for the trading platform
        }

    def _post(self, endpoint: str, json_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = requests.post(f"{self.base_url}{endpoint}", json=json_data, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            return {"error": "Request to MT5 API service timed out."}
        except requests.exceptions.RequestException as e:
            return {"error": f"Request to MT5 API service failed: {e}"}

    def connect(self) -> Dict[str, Any]:
        return self._post("/mt5/connect", self._get_auth_payload())

    def get_account_info(self) -> Dict[str, Any]:
        return self._post("/mt5/account_info", self._get_auth_payload())

    def get_open_positions(self) -> Dict[str, Any]:
        return self._post("/mt5/positions/open", self._get_auth_payload())

    def get_position_by_ticket(self, ticket: int) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload["position_ticket"] = ticket
        return self._post("/mt5/positions/details", payload)

    def place_trade(self, symbol: str, lot_size: float, direction: str, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "symbol": symbol,
            "lot_size": lot_size,
            "direction": direction,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        })
        return self._post("/mt5/trade", json_data=payload)

    def close_trade(self, ticket: int, volume: float, symbol: str) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "ticket": ticket,
            "volume": volume,
            "symbol": symbol,
        })
        return self._post("/mt5/positions/close", payload)

    def modify_position_protection(self, position_id: int, symbol: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "position_id": position_id,
            "symbol": symbol,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        })
        return self._post("/mt5/positions/modify_protection", payload)

    def get_live_price(self, symbol: str) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload["symbol"] = symbol
        return self._post("/mt5/price", json_data=payload)

    def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload["symbol"] = symbol
        return self._post("/mt5/symbol_info", payload)

    def fetch_trade_sync_data(self, position_id: int, instrument_symbol: str) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "position_id": position_id,
            "instrument_symbol": instrument_symbol,
        })
        return self._post("/mt5/deals/sync_data", payload)

    def get_historical_candles(self, symbol: str, timeframe: str, count: int) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "symbol": symbol,
            "timeframe": timeframe,
            "count": count,
        })
        return self._post("/mt5/candles", json_data=payload)
