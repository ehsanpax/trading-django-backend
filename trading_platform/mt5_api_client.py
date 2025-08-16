import requests
import json
import asyncio
import websockets
import uuid
import logging
from typing import Dict, Any, Optional, Callable, List, Tuple, Set
from datetime import datetime
from trades.exceptions import BrokerAPIError, BrokerConnectionError
import os

# Feature flag: Disable MT5 WebSocket path from Django to MT5.
# To re-activate the WebSocket path, set environment variable MT5_WS_ENABLED=1 (or true/yes) and restart the backend.
MT5_WS_ENABLED = os.getenv("MT5_WS_ENABLED", "0").lower() in ("1", "true", "yes")

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
        self.closed_position_listeners: List[Callable] = []

    def _get_auth_payload(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "password": self.password,
            "broker_server": self.broker_server,
            "internal_account_id": self.internal_account_id,
        }

    async def manage_connection(self):
        # WebSocket path disabled: rely on RabbitMQ/HTTP updates instead.
        # To re-activate, set MT5_WS_ENABLED=1 and restart.
        if not MT5_WS_ENABLED:
            return
        ws_url = f"{self.ws_base_url}/ws/{self.internal_account_id}/{self.client_id}"
        while True:
            try:
                # Add ping_interval to keep the connection alive
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.ws = ws
                    self.is_connected = True
                    logger.debug(f"MT5 WS connected internal_account_id={self.internal_account_id}")

                    # Resubscribe to all necessary data upon connection
                    for symbol in self.price_listeners.keys():
                        logger.debug(f"Resubscribe price {symbol} for {self.internal_account_id}")
                        await self.subscribe_price(symbol)
                    
                    for listener_key in self.candle_listeners.keys():
                        # Use rsplit to tolerate symbols that may contain underscores
                        try:
                            symbol, timeframe = listener_key.rsplit('_', 1)
                        except ValueError:
                            # Fallback to original split if unexpected format
                            parts = listener_key.split('_')
                            symbol, timeframe = parts[0], parts[-1]
                        logger.debug(f"Resubscribe candles {symbol}@{timeframe} for {self.internal_account_id}")
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
                                    try:
                                        if asyncio.iscoroutinefunction(listener):
                                            await listener(self.last_account_info)
                                        else:
                                            listener(self.last_account_info)
                                    except Exception as cb_e:
                                        logger.warning(f"account_info listener error: {cb_e}")
                            elif message_type == "open_positions":
                                positions_list = data.get("data", {}).get("open_positions", [])
                                if not isinstance(positions_list, list):
                                    logger.error(f"Expected 'open_positions' to be a list, got {type(positions_list)}")
                                    positions_list = []
                                final_positions = [item for item in positions_list if isinstance(item, dict)]
                                self.last_open_positions = final_positions
                                logger.info(f"MT5 WS open_positions len={len(final_positions)} for {self.internal_account_id}")
                                for listener in self.open_positions_listeners:
                                    try:
                                        if asyncio.iscoroutinefunction(listener):
                                            await listener(self.last_open_positions)
                                        else:
                                            listener(self.last_open_positions)
                                    except Exception as cb_e:
                                        logger.warning(f"open_positions listener error: {cb_e}")
                            elif message_type == "closed_position":
                                closed_deal_data = data.get("data", {})
                                for listener in self.closed_position_listeners:
                                    try:
                                        if asyncio.iscoroutinefunction(listener):
                                            await listener(closed_deal_data)
                                        else:
                                            listener(closed_deal_data)
                                    except Exception as cb_e:
                                        logger.warning(f"closed_position listener error: {cb_e}")
                            elif message_type == "live_price":
                                price_data = data.get("data", {})
                                symbol = price_data.get("symbol")
                                if symbol:
                                    self.last_prices[symbol] = price_data
                                    for listener in self.price_listeners.get(symbol, []):
                                        try:
                                            if asyncio.iscoroutinefunction(listener):
                                                await listener(price_data)
                                            else:
                                                listener(price_data)
                                        except Exception as cb_e:
                                            logger.warning(f"price listener error: {cb_e}")
                            elif message_type == "candle_update":
                                symbol = data.get("symbol")
                                timeframe = data.get("timeframe")
                                candle_data = data.get("data", {})
                                logger.debug(f"MT5 WS candle_update {symbol}@{timeframe} for {self.internal_account_id}")
                                if symbol and timeframe:
                                    listener_key = f"{symbol}_{timeframe}"
                                    for listener in self.candle_listeners.get(listener_key, []):
                                        try:
                                            if asyncio.iscoroutinefunction(listener):
                                                await listener(candle_data)
                                            else:
                                                listener(candle_data)
                                        except Exception as cb_e:
                                            logger.warning(f"candle listener error: {cb_e}")
                        except websockets.exceptions.ConnectionClosed as e:
                            break
                        except Exception as e:
                            logger.error(f"Error in MT5 WS listener {self.internal_account_id}: {e}")
                            break

            except Exception as e:
                logger.error(f"MT5 WS connect failed for {self.internal_account_id}: {e}")
            
            finally:
                self.is_connected = False
                self.ws = None
                logger.debug(f"MT5 WS reconnect in 5s internal_account_id={self.internal_account_id}")
                await asyncio.sleep(5)

    async def subscribe_price(self, symbol: str):
        # No-op when WS path is disabled.
        if not MT5_WS_ENABLED:
            return
        if self.is_connected:
            try:
                message = json.dumps({"type": "subscribe_price", "symbol": symbol})
                logger.debug(f"MT5 WS send subscribe_price {symbol} for {self.internal_account_id}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not subscribe to {symbol}, connection closed.")

    async def unsubscribe_price(self, symbol: str):
        # No-op when WS path is disabled.
        if not MT5_WS_ENABLED:
            return
        if self.is_connected:
            try:
                message = json.dumps({"type": "unsubscribe_price", "symbol": symbol})
                logger.debug(f"MT5 WS send unsubscribe_price {symbol} for {self.internal_account_id}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not unsubscribe from {symbol}, connection closed.")

    async def subscribe_candles(self, symbol: str, timeframe: str):
        # No-op when WS path is disabled.
        if not MT5_WS_ENABLED:
            return
        if self.is_connected:
            try:
                message = json.dumps({"type": "subscribe_candles", "symbol": symbol, "timeframe": timeframe})
                logger.debug(f"MT5 WS send subscribe_candles {symbol}@{timeframe} for {self.internal_account_id}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not subscribe to candles for {symbol}_{timeframe}, connection closed.")

    async def unsubscribe_candles(self, symbol: str, timeframe: str):
        # No-op when WS path is disabled.
        if not MT5_WS_ENABLED:
            return
        if self.is_connected:
            try:
                message = json.dumps({"type": "unsubscribe_candles", "symbol": symbol, "timeframe": timeframe})
                logger.debug(f"MT5 WS send unsubscribe_candles {symbol}@{timeframe} for {self.internal_account_id}")
                await self.ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"Could not unsubscribe from candles for {symbol}_{timeframe}, connection closed.")

    def register_price_listener(self, symbol: str, callback: Callable):
        if symbol not in self.price_listeners:
            self.price_listeners[symbol] = []
        # Avoid duplicate registrations
        if callback not in self.price_listeners[symbol]:
            self.price_listeners[symbol].append(callback)

    def unregister_price_listener(self, symbol: str, callback: Callable):
        # Make idempotent and safe
        listeners = self.price_listeners.get(symbol)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            # Already removed or never registered
            return
        if not listeners:
            # Clean up empty key
            self.price_listeners.pop(symbol, None)

    def register_candle_listener(self, symbol: str, timeframe: str, callback: Callable):
        listener_key = f"{symbol}_{timeframe}"
        if listener_key not in self.candle_listeners:
            self.candle_listeners[listener_key] = []
        # Avoid duplicate registrations
        if callback not in self.candle_listeners[listener_key]:
            self.candle_listeners[listener_key].append(callback)

    def unregister_candle_listener(self, symbol: str, timeframe: str, callback: Callable):
        listener_key = f"{symbol}_{timeframe}"
        listeners = self.candle_listeners.get(listener_key)
        if not listeners:
            return
        try:
            listeners.remove(callback)
        except ValueError:
            # Already removed or never registered
            return
        if not listeners:
            self.candle_listeners.pop(listener_key, None)

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

    def register_closed_position_listener(self, callback: Callable):
        self.closed_position_listeners.append(callback)

    def unregister_closed_position_listener(self, callback: Callable):
        if callback in self.closed_position_listeners:
            self.closed_position_listeners.remove(callback)

    def get_account_info(self) -> Dict[str, Any]:
        return self.last_account_info

    def get_open_positions(self) -> Dict[str, Any]:
        return {"open_positions": self.last_open_positions}

    def get_live_price(self, symbol: str) -> Dict[str, Any]:
        if symbol in self.last_prices:
            return self.last_prices[symbol]
        logger.warning(f"Cache miss for {symbol}. Falling back to HTTP request for live price.")
        payload = self._get_auth_payload()
        payload["symbol"] = symbol
        return self._post("/mt5/price", json_data=payload)

    # --- HTTP Methods for one-off actions ---

    def _post(self, endpoint: str, json_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            headers = {'Content-Type': 'application/json'}
            url = f"{self.base_url}{endpoint}"
            logger.info(f"MT5APIClient: Making POST request to {url}")
            response = requests.post(
                url,
                json=json_data,
                headers=headers,
                timeout=10
            )
            if not response.ok:
                try:
                    error_data = response.json()
                    error_message = error_data.get("detail", "No detail provided")
                    if isinstance(error_message, list) and error_message:
                        error_message = error_message[0].get("msg", str(error_message))
                    raise BrokerAPIError(f"MT5 API Error: {error_message} (Status {response.status_code})")
                except json.JSONDecodeError:
                    raise BrokerAPIError(f"MT5 API Error: {response.text} (Status {response.status_code})")

            data = response.json()
            #logger.info(f"Response from MT5 API ({endpoint}): {data}")
            return data
        except requests.exceptions.Timeout as e:
            raise BrokerConnectionError("Request to MT5 API service timed out.") from e
        except requests.exceptions.RequestException as e:
            raise BrokerConnectionError(f"Request to MT5 API service failed: {e}") from e

    def _delete(self, endpoint: str) -> Dict[str, Any]:
        try:
            response = requests.delete(f"{self.base_url}{endpoint}", timeout=10)
            if not response.ok:
                try:
                    error_data = response.json()
                    error_message = error_data.get("detail", "No detail provided")
                    if isinstance(error_message, list) and error_message:
                        error_message = error_message[0].get("msg", str(error_message))
                    raise BrokerAPIError(f"MT5 API Error: {error_message} (Status {response.status_code})")
                except json.JSONDecodeError:
                    raise BrokerAPIError(f"MT5 API Error: {response.text} (Status {response.status_code})")

            data = response.json()
            logger.info(f"Response from MT5 API ({endpoint}): {data}")
            return data
        except requests.exceptions.Timeout as e:
            raise BrokerConnectionError("Request to MT5 API service timed out.") from e
        except requests.exceptions.RequestException as e:
            raise BrokerConnectionError(f"Request to MT5 API service failed: {e}") from e

    def _get(self, endpoint: str) -> Dict[str, Any]:
        try:
            response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
            if not response.ok:
                try:
                    error_data = response.json()
                    error_message = error_data.get("detail", "No detail provided")
                    if isinstance(error_message, list) and error_message:
                        error_message = error_message[0].get("msg", str(error_message))
                    raise BrokerAPIError(f"MT5 API Error: {error_message} (Status {response.status_code})")
                except json.JSONDecodeError:
                    raise BrokerAPIError(f"MT5 API Error: {response.text} (Status {response.status_code})")
            return response.json()
        except requests.exceptions.Timeout as e:
            raise BrokerConnectionError("Request to MT5 API service timed out.") from e
        except requests.exceptions.RequestException as e:
            raise BrokerConnectionError(f"Request to MT5 API service failed: {e}") from e

    def connect(self) -> Dict[str, Any]:
        return self._post("/mt5/connect", self._get_auth_payload())

    def get_position_by_ticket(self, ticket: int) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload["position_ticket"] = ticket
        return self._post("/mt5/positions/details", payload)

    def get_all_open_positions_rest(self) -> Dict[str, Any]:
        """
        Fetches all open positions and pending orders via REST API.
        """
        return self._post("/mt5/positions/open", self._get_auth_payload())

    def get_account_info_rest(self) -> Dict[str, Any]:
        """Fetch account info via REST for sync contexts."""
        return self._post("/mt5/account_info", self._get_auth_payload())

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
        #logger.info(f"Sending trade request to MT5 API: {payload}")
        return self._post("/mt5/trade", json_data=payload)

    def close_trade(self, ticket: int, volume: float, symbol: str) -> Dict[str, Any]:
        payload = self._get_auth_payload()
        payload.update({
            "ticket": ticket,
            "volume": volume,
            "symbol": symbol,
        })
        return self._post("/mt5/positions/close", payload)

    def cancel_order(self, order_ticket: int) -> Dict[str, Any]:
        """
        Cancels a pending order.
        """
        payload = self._get_auth_payload()
        payload["order_ticket"] = order_ticket
        return self._post("/mt5/orders/cancel", json_data=payload)

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

    def close_instance(self, internal_account_id: str) -> Dict[str, Any]:
        payload = {"internal_account_id": internal_account_id}
        return self._post("/mt5/close", json_data=payload)

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
            #logger.info(f"Successfully triggered instance initialization for {self.internal_account_id}")
        except Exception as e:
            logger.error(f"Failed to trigger instance initialization for {self.internal_account_id}: {e}")
            # We don't re-raise here, as the connection might still succeed.
            # The error will be handled by downstream logic if it's critical.

    # --- Headless polling control (HTTP) ---
    def start_headless_poller(self) -> Dict[str, Any]:
        """Start the MT5 headless data/position poller for this account."""
        return self._post("/mt5/headless/poller/start", self._get_auth_payload())

    def headless_subscribe_price(self, symbol: str) -> Dict[str, Any]:
        """Subscribe to price ticks for a symbol (headless mode)."""
        payload = self._get_auth_payload()
        payload["symbol"] = symbol or ""
        return self._post("/mt5/headless/subscribe/price", payload)

    def headless_unsubscribe_price(self, symbol: str) -> Dict[str, Any]:
        """Unsubscribe from price ticks for a symbol (headless mode)."""
        payload = self._get_auth_payload()
        payload["symbol"] = symbol or ""
        return self._post("/mt5/headless/unsubscribe/price", payload)

    def headless_subscribe_candles(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """Subscribe to candle updates for a symbol@timeframe (headless mode)."""
        payload = self._get_auth_payload()
        payload.update({
            "symbol": symbol or "",
            "timeframe": timeframe or "",
        })
        return self._post("/mt5/headless/subscribe/candles", payload)

    def headless_unsubscribe_candles(self, symbol: str, timeframe: str) -> Dict[str, Any]:
        """Unsubscribe from candle updates for a symbol@timeframe (headless mode)."""
        payload = self._get_auth_payload()
        payload.update({
            "symbol": symbol or "",
            "timeframe": timeframe or "",
        })
        return self._post("/mt5/headless/unsubscribe/candles", payload)

# --- Connection Manager ---
class _MT5ConnectionManager:
    def __init__(self):
        self._connections: Dict[str, MT5APIClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str) -> MT5APIClient:
        async with self._lock:
            if internal_account_id not in self._connections:
                client = MT5APIClient(base_url, account_id, password, broker_server, internal_account_id)
                if MT5_WS_ENABLED:
                    asyncio.create_task(client.manage_connection())
                    self._connections[internal_account_id] = client
                    # Give it a moment to establish the initial connection
                    await asyncio.sleep(1)
                    # Subscribe to a default symbol to kick-start the server's polling loop
                    await client.subscribe_price("EURUSD")
                else:
                    # WebSocket path disabled: do not start the WS task.
                    # To re-activate, set MT5_WS_ENABLED=1 and restart the backend.
                    self._connections[internal_account_id] = client
            return self._connections[internal_account_id]

connection_manager = _MT5ConnectionManager()

# --- Headless Orchestrator (platform-agnostic, MT5-specific, lives here) ---
class MT5HeadlessOrchestrator:
    """
    Manages headless poller lifecycle and ref-counted subscriptions per account.
    Keeps all MT5-related orchestration inside this module.
    """
    def __init__(self):
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._ready_accounts: Set[str] = set()
        self._price_refs: Dict[str, Dict[str, int]] = {}
        self._candle_refs: Dict[str, Dict[Tuple[str, str], int]] = {}

    def _get_lock(self, internal_account_id: str) -> asyncio.Lock:
        lock = self._account_locks.get(internal_account_id)
        if lock is None:
            lock = asyncio.Lock()
            self._account_locks[internal_account_id] = lock
        return lock

    async def _run_blocking(self, fn: Callable, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def ensure_ready(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str) -> MT5APIClient:
        """Ensure client exists and headless poller started."""
        lock = self._get_lock(internal_account_id)
        async with lock:
            client = await connection_manager.get_client(base_url, account_id, password, broker_server, internal_account_id)
            if internal_account_id not in self._ready_accounts:
                try:
                    await self._run_blocking(client.start_headless_poller)
                    self._ready_accounts.add(internal_account_id)
                    logger.debug(f"Headless poller started for {internal_account_id}")
                except Exception as e:
                    logger.warning(f"Failed to start headless poller for {internal_account_id}: {e}")
            return client

    async def subscribe_price(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str) -> int:
        symbol = symbol or ""
        client = await self.ensure_ready(base_url, account_id, password, broker_server, internal_account_id)
        lock = self._get_lock(internal_account_id)
        async with lock:
            refs = self._price_refs.setdefault(internal_account_id, {})
            count = refs.get(symbol, 0)
            if count == 0:
                try:
                    await self._run_blocking(client.headless_subscribe_price, symbol)
                except BrokerAPIError as e:
                    # Treat duplicate/409 as ok
                    if "409" not in str(e):
                        raise
            refs[symbol] = count + 1
            return refs[symbol]

    async def unsubscribe_price(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str) -> int:
        symbol = symbol or ""
        client = await self.ensure_ready(base_url, account_id, password, broker_server, internal_account_id)
        lock = self._get_lock(internal_account_id)
        async with lock:
            refs = self._price_refs.setdefault(internal_account_id, {})
            count = refs.get(symbol, 0)
            new_count = max(0, count - 1)
            if count > 0 and new_count == 0:
                try:
                    await self._run_blocking(client.headless_unsubscribe_price, symbol)
                except BrokerAPIError as e:
                    if "404" not in str(e):
                        raise
                refs.pop(symbol, None)
            else:
                refs[symbol] = new_count
            return new_count

    async def subscribe_candles(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str, timeframe: str) -> int:
        symbol = symbol or ""
        timeframe = timeframe or ""
        client = await self.ensure_ready(base_url, account_id, password, broker_server, internal_account_id)
        lock = self._get_lock(internal_account_id)
        async with lock:
            refs = self._candle_refs.setdefault(internal_account_id, {})
            key = (symbol, timeframe)
            count = refs.get(key, 0)
            if count == 0:
                try:
                    await self._run_blocking(client.headless_subscribe_candles, symbol, timeframe)
                except BrokerAPIError as e:
                    if "409" not in str(e):
                        raise
            refs[key] = count + 1
            return refs[key]

    async def unsubscribe_candles(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str, timeframe: str) -> int:
        symbol = symbol or ""
        timeframe = timeframe or ""
        client = await self.ensure_ready(base_url, account_id, password, broker_server, internal_account_id)
        lock = self._get_lock(internal_account_id)
        async with lock:
            refs = self._candle_refs.setdefault(internal_account_id, {})
            key = (symbol, timeframe)
            count = refs.get(key, 0)
            new_count = max(0, count - 1)
            if count > 0 and new_count == 0:
                try:
                    await self._run_blocking(client.headless_unsubscribe_candles, symbol, timeframe)
                except BrokerAPIError as e:
                    if "404" not in str(e):
                        raise
                refs.pop(key, None)
            else:
                refs[key] = new_count
            return new_count

    async def subscriptions_status(self, base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str) -> Dict[str, Any]:
        client = await self.ensure_ready(base_url, account_id, password, broker_server, internal_account_id)
        try:
            return await self._run_blocking(client.headless_subscriptions_status)
        except Exception as e:
            logger.warning(f"Failed to fetch subscriptions status for {internal_account_id}: {e}")
            return {"error": str(e)}

# Singleton orchestrator
mt5_headless_orchestrator = MT5HeadlessOrchestrator()

# Convenience async helpers (exported)
async def mt5_ensure_ready(base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str) -> MT5APIClient:
    return await mt5_headless_orchestrator.ensure_ready(base_url, account_id, password, broker_server, internal_account_id)

async def mt5_subscribe_price(base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str) -> int:
    return await mt5_headless_orchestrator.subscribe_price(base_url, account_id, password, broker_server, internal_account_id, symbol)

async def mt5_unsubscribe_price(base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str) -> int:
    return await mt5_headless_orchestrator.unsubscribe_price(base_url, account_id, password, broker_server, internal_account_id, symbol)

async def mt5_subscribe_candles(base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str, timeframe: str) -> int:
    return await mt5_headless_orchestrator.subscribe_candles(base_url, account_id, password, broker_server, internal_account_id, symbol, timeframe)

async def mt5_unsubscribe_candles(base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str, symbol: str, timeframe: str) -> int:
    return await mt5_headless_orchestrator.unsubscribe_candles(base_url, account_id, password, broker_server, internal_account_id, symbol, timeframe)

async def mt5_subscriptions_status(base_url: str, account_id: int, password: str, broker_server: str, internal_account_id: str) -> Dict[str, Any]:
    return await mt5_headless_orchestrator.subscriptions_status(base_url, account_id, password, broker_server, internal_account_id)
