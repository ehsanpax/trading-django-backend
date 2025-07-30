import requests
import json
import asyncio
import websockets
import uuid
import logging
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime

logger = logging.getLogger(__name__)

class MT5APIClient:
    def __init__(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str):
        self.base_url = base_url
        self.ws_base_url = base_url.replace("http", "ws")
        self.account_id = account_id
        self.password = password
        self.broker_server = broker_server
        self.internal_account_id = internal_account_id
        self.client_id = str(uuid.uuid4())
        self.ws = None
        self.is_connected = False
        self.initial_data_received = asyncio.Event()

        # Data stores
        self.last_account_info: Dict[str, Any] = {}
        self.last_open_positions: List[Dict[str, Any]] = []
        self.last_prices: Dict[str, Dict[str, Any]] = {}

        # Listeners
        self.price_listeners: Dict[str, List[Callable]] = {}
        self.candle_listeners: Dict[str, List[Callable]] = {} # Key: "symbol_timeframe"
        self.account_info_listeners: List[Callable] = []
        self.open_positions_listeners: List[Callable] = []

    def _get_auth_payload(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "password": self.password,
            "broker_server": self.broker_server,
            "internal_account_id": self.internal_account_id,
        }

    async def manage_connection(self):
        ws_url = f"{self.ws_base_url}/ws/{self.internal_account_id}/{self.client_id}"
        while True:
            try:
                # Add ping_interval to keep the connection alive
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.ws = ws
                    self.is_connected = True
                    logger.info(f"WebSocket connected for account {self.internal_account_id}")

                    # Resubscribe to all necessary data upon connection
                    for symbol in self.price_listeners.keys():
                        await self.subscribe_price(symbol)
                    
                    for listener_key in self.candle_listeners.keys():
                        symbol, timeframe = listener_key.split('_')
                        await self.subscribe_candles(symbol, timeframe)

                    while self.is_connected:
                        try:
                            message = await self.ws.recv()
                            data = json.loads(message)
                            message_type = data.get("type")

                            if message_type == "account_info":
                                self.last_account_info = data.get("data", {})
                                if not self.initial_data_received.is_set():
                                    self.initial_data_received.set()
                                for listener in self.account_info_listeners:
                                    await listener(self.last_account_info)
                            elif message_type == "open_positions":
                                positions_list = data.get("data", {}).get("open_positions", [])
                                if not isinstance(positions_list, list):
                                    logger.error(f"MT5APIClient: Expected 'open_positions' to be a list, but got {type(positions_list)}: {positions_list}")
                                    positions_list = []
                                final_positions = [item for item in positions_list if isinstance(item, dict)]
                                self.last_open_positions = final_positions
                                for listener in self.open_positions_listeners:
                                    await listener(self.last_open_positions)
                            elif message_type == "live_price":
                                price_data = data.get("data", {})
                                symbol = price_data.get("symbol")
                                if symbol:
                                    self.last_prices[symbol] = price_data
                                    if symbol in self.price_listeners:
                                        for listener in self.price_listeners[symbol]:
                                            await listener(price_data)
                            elif message_type == "candle_update":
                                symbol = data.get("symbol")
                                timeframe = data.get("timeframe")
                                candle_data = data.get("data", {})
                                if symbol and timeframe:
                                    listener_key = f"{symbol}_{timeframe}"
                                    if listener_key in self.candle_listeners:
                                        for listener in self.candle_listeners[listener_key]:
                                            await listener(candle_data)
                        except websockets.exceptions.ConnectionClosed as e:
                            logger.warning(f"WebSocket connection closed for account {self.internal_account_id}. Code: {e.code}, Reason: {e.reason}")
                            break
                        except Exception as e:
                            logger.error(f"Error in WebSocket listener for account {self.internal_account_id}: {e}")
                            break

            except Exception as e:
                logger.error(f"WebSocket connection failed for account {self.internal_account_id}: {e}")
            
            finally:
                self.is_connected = False
                self.ws = None
                logger.info(f"Attempting to reconnect in 5 seconds for account {self.internal_account_id}...")
                await asyncio.sleep(5)

    async def subscribe_price(self, symbol: str):
        if self.is_connected:
            try:
                message = json.dumps({"type": "subscribe_price", "symbol": symbol})
                #logger.info(f"Sending WebSocket message for account {self.internal_account_id}: {message}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not subscribe to {symbol}, connection closed.")

    async def unsubscribe_price(self, symbol: str):
        if self.is_connected:
            try:
                message = json.dumps({"type": "unsubscribe_price", "symbol": symbol})
                logger.info(f"Sending unsubscribe_price message for {symbol} to MT5 API for account {self.internal_account_id}: {message}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not unsubscribe from {symbol}, connection closed.")

    async def subscribe_candles(self, symbol: str, timeframe: str):
        if self.is_connected:
            try:
                message = json.dumps({"type": "subscribe_candles", "symbol": symbol, "timeframe": timeframe})
                #logger.info(f"Sending WebSocket message for account {self.internal_account_id}: {message}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not subscribe to candles for {symbol}_{timeframe}, connection closed.")

    async def unsubscribe_candles(self, symbol: str, timeframe: str):
        if self.is_connected:
            try:
                message = json.dumps({"type": "unsubscribe_candles", "symbol": symbol, "timeframe": timeframe})
                logger.info(f"Sending unsubscribe_candles message for {symbol}_{timeframe} to MT5 API for account {self.internal_account_id}: {message}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not unsubscribe from candles for {symbol}_{timeframe}, connection closed.")

    def register_price_listener(self, symbol: str, callback: Callable):
        if symbol not in self.price_listeners:
            self.price_listeners[symbol] = []
        self.price_listeners[symbol].append(callback)

    def unregister_price_listener(self, symbol: str, callback: Callable):
        if symbol in self.price_listeners:
            self.price_listeners[symbol].remove(callback)

    def register_candle_listener(self, symbol: str, timeframe: str, callback: Callable):
        listener_key = f"{symbol}_{timeframe}"
        if listener_key not in self.candle_listeners:
            self.candle_listeners[listener_key] = []
        self.candle_listeners[listener_key].append(callback)

    def unregister_candle_listener(self, symbol: str, timeframe: str, callback: Callable):
        listener_key = f"{symbol}_{timeframe}"
        if listener_key in self.candle_listeners:
            self.candle_listeners[listener_key].remove(callback)

    def register_account_info_listener(self, callback: Callable):
        self.account_info_listeners.append(callback)

    def unregister_account_info_listener(self, callback: Callable):
        if callback in self.account_info_listeners:
            self.account_info_listeners.remove(callback)

    def register_open_positions_listener(self, callback: Callable):
        self.open_positions_listeners.append(callback)

    def unregister_open_positions_listener(self, callback: Callable):
        if callback in self.open_positions_listeners:
            self.open_positions_listeners.remove(callback)

    def get_account_info(self) -> Dict[str, Any]:
        # Returns the last known info, does not poll
        return self.last_account_info

    def get_open_positions(self) -> Dict[str, Any]:
        # Returns the last known positions, does not poll
        return {"open_positions": self.last_open_positions}

    def get_live_price(self, symbol: str) -> Dict[str, Any]:
        """
        Gets the live price for a symbol.
        First, checks the WebSocket cache. If not found, falls back to a direct HTTP request.
        """
        # Check cache first
        if symbol in self.last_prices:
            return self.last_prices[symbol]

        # If not in cache, fall back to HTTP request
        logger.warning(f"Cache miss for {symbol}. Falling back to HTTP request for live price.")
        payload = self._get_auth_payload()
        payload["symbol"] = symbol
        
        # Ensure this symbol is subscribed to for future requests
        asyncio.run(self.subscribe_price(symbol))
        
        return self._post("/mt5/price", json_data=payload)

    # --- HTTP Methods for one-off actions ---

    def _post(self, endpoint: str, json_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            logger.info(f"Sending POST request to {endpoint} with data: {json_data}")
            headers = {'Content-Type': 'application/json'}
            response = requests.post(
                f"{self.base_url}{endpoint}",
                json=json_data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            return {"error": "Request to MT5 API service timed out."}
        except requests.exceptions.RequestException as e:
            return {"error": f"Request to MT5 API service failed: {e}"}

    def _delete(self, endpoint: str) -> Dict[str, Any]:
        try:
            response = requests.delete(f"{self.base_url}{endpoint}", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            return {"error": "Request to MT5 API service timed out."}
        except requests.exceptions.RequestException as e:
            return {"error": f"Request to MT5 API service failed: {e}"}

    def connect(self) -> Dict[str, Any]:
        return self._post("/mt5/connect", self._get_auth_payload())

    def get_position_by_ticket(self, ticket: int) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload["position_ticket"] = ticket
        return self._post("/mt5/positions/details", payload)

    def place_trade(self, symbol: str, lot_size: float, direction: str, stop_loss: float, take_profit: float, order_type: str = "MARKET", limit_price: Optional[float] = None) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "symbol": symbol,
            "lot_size": lot_size,
            "direction": direction,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "order_type": order_type,
            "limit_price": limit_price,
        })
        logger.info(f"Sending trade request to MT5 API: {payload}")
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

    def get_historical_candles(self, symbol: str, timeframe: str, count: Optional[int] = None, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "symbol": symbol,
            "timeframe": timeframe,
        })
        if count is not None:
            payload["count"] = count
        elif start_time is not None and end_time is not None:
            payload["start_time"] = start_time.isoformat()
            payload["end_time"] = end_time.isoformat()
        else:
            return {"error": "Either 'count' or both 'start_time' and 'end_time' must be provided."}
            
        return self._post("/mt5/candles", json_data=payload)

    def delete_instance(self) -> Dict[str, Any]:
        return self._delete(f"/mt5/instance/{self.internal_account_id}")

    async def trigger_instance_initialization(self):
        """
        Makes a simple, one-off HTTP request to the MT5 service to ensure
        the MT5 instance is started and authenticated. This is used to "wake up"
        the instance before WebSocket listeners expect data.
        """
        loop = asyncio.get_event_loop()
        try:
            # Use a simple endpoint like /mt5/account_info which requires authentication
            # but is lightweight. We discard the result; the goal is just to make the call.
            await loop.run_in_executor(
                None, 
                lambda: self._post("/mt5/account_info", self._get_auth_payload())
            )
            logger.info(f"Successfully triggered instance initialization for {self.internal_account_id}")
        except Exception as e:
            logger.error(f"Failed to trigger instance initialization for {self.internal_account_id}: {e}")
            # We don't re-raise here, as the connection might still succeed.
            # The error will be handled by downstream logic if it's critical.

# --- Connection Manager ---
class _MT5ConnectionManager:
    def __init__(self):
        self._connections: Dict[str, MT5APIClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str) -> MT5APIClient:
        async with self._lock:
            if internal_account_id not in self._connections:
                client = MT5APIClient(base_url, account_id, password, broker_server, internal_account_id)
                asyncio.create_task(client.manage_connection())
                self._connections[internal_account_id] = client
                # Give it a moment to establish the initial connection
                await asyncio.sleep(1)
                # Subscribe to a default symbol to kick-start the server's polling loop
                await client.subscribe_price("EURUSD")
            return self._connections[internal_account_id]

connection_manager = _MT5ConnectionManager()
