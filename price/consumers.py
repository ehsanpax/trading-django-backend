# price/consumers.py
import asyncio
import json
import logging
import pandas as pd
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account, MT5Account, CTraderAccount
from trading_platform.mt5_api_client import MT5APIClient, connection_manager
from django.conf import settings
import websockets, aiohttp
from datetime import datetime, timedelta
from indicators.services import IndicatorService

logger = logging.getLogger(__name__)

class PriceConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeframe = None
        self.price_task = None
        self.indicator_service = IndicatorService()
        self.active_indicators = {}
        self.historical_data = pd.DataFrame()
        self.mt5_client = None

    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]

        await self.accept()
        
        if not self.account_id:
            await self.send_json({"error": "Account ID not provided"})
            await self.close()
            return
            
        #logger.info(f"✅ WebSocket connection established for Account: {self.account_id} - {self.symbol}")

        # Fetch the account from the database using async ORM (via sync_to_async)
        self.account = await sync_to_async(Account.objects.filter(id=self.account_id).first)()
        if not self.account:
            await self.send_json({"error": "Invalid account ID"})
            await self.close()
            return

        self.platform = self.account.platform.upper()

        if self.platform == "MT5":
            self.mt5_account = await sync_to_async(MT5Account.objects.filter(account_id=self.account.id).first)()
            if not self.mt5_account:
                await self.send_json({"error": "No MT5 account found"})
                await self.close()
                return

            try:
                self.mt5_client = await connection_manager.get_client(
                    base_url=settings.MT5_API_BASE_URL,
                    account_id=self.mt5_account.account_number,
                    password=self.mt5_account.encrypted_password,
                    broker_server=self.mt5_account.broker_server,
                    internal_account_id=str(self.account.id)
                )
                self.mt5_client.register_price_listener(self.symbol, self.send_price_update)
                # The candle listener will be registered when a timeframe is subscribed to.
                await self.mt5_client.subscribe_price(self.symbol)
            except ConnectionError as e:
                await self.send_json({"error": str(e)})
                await self.close()
                return

        elif self.platform == "CTRADER":
            ctrader_account = await sync_to_async(lambda: self.account.ctrader_account)()
            if not ctrader_account:
                await self.send_json({"error": "No linked CTRADER account found"})
                await self.close()
                return

            self.ctrader_access_token = ctrader_account.access_token
            self.ctid_trader_account_id = ctrader_account.ctid_trader_account_id
            if not self.ctrader_access_token or not self.ctid_trader_account_id:
                await self.send_json({"error": "Missing CTRADER credentials on account"})
                await self.close()
                return

            if not await self.subscribe_ctrader():
                await self.close()
                return

            self.price_task = asyncio.create_task(self.ctrader_price_stream())

        else:
            await self.send_json({"error": "Unsupported trading platform"})
            await self.close()
            return

    async def disconnect(self, close_code):
        logger.info(f"🔻 WebSocket disconnected for Account: {self.account_id} - {self.symbol}")
        if self.platform == "MT5" and self.mt5_client:
            self.mt5_client.unregister_price_listener(self.symbol, self.send_price_update)
            if self.timeframe: # If we were subscribed to candles, unregister
                self.mt5_client.unregister_candle_listener(self.symbol, self.timeframe, self.send_candle_update)
        elif self.price_task:
            self.price_task.cancel()
        logger.info(f"🔻 WebSocket closed for Account: {self.account_id} - {self.symbol}")

    async def receive_json(self, content):
        logger.info(f"Received message from client for account {self.account_id} - {self.symbol}: {json.dumps(content)}")
        action = content.get("type") or content.get("action")

        if action == "subscribe":
            new_timeframe = content.get("timeframe") or content.get("params", {}).get("timeframe")
            if new_timeframe and new_timeframe != self.timeframe:
                # If changing timeframe, unsubscribe from old one first
                if self.timeframe and self.mt5_client:
                    await self.mt5_client.unsubscribe_candles(self.symbol, self.timeframe)
                    self.mt5_client.unregister_candle_listener(self.symbol, self.timeframe, self.send_candle_update)

                self.timeframe = new_timeframe
                logger.info(f"Subscribed to timeframe: {self.timeframe}")
                if self.mt5_client:
                    self.mt5_client.register_candle_listener(self.symbol, self.timeframe, self.send_candle_update)
                    await self.mt5_client.subscribe_candles(self.symbol, self.timeframe)

        elif action == "add_indicator":
            await self.handle_add_indicator(content)

        elif action == "remove_indicator":
            await self.handle_remove_indicator(content)

        elif action == "unsubscribe":
            await self.handle_unsubscribe(content)

        else:
            logger.warning(f"Received unknown action: {action}")

    async def handle_add_indicator(self, content):
        indicator_name = content.get("indicator")
        params = content.get("params", {})
        unique_id = content.get("unique_id") # Capture the unique_id
        
        if not indicator_name:
            await self.send_json({"error": "Indicator name not provided"})
            return

        if not unique_id:
            await self.send_json({"error": "Unique ID not provided for indicator"})
            return

        logger.info(f"Adding indicator: {indicator_name} with params: {params}, unique_id: {unique_id}")
        self.active_indicators[unique_id] = {"name": indicator_name, "params": params} # Store by unique_id
        
        # Fetch historical data to calculate the indicator
        await self.fetch_and_calculate_initial_indicator(unique_id, indicator_name, params)

    async def fetch_and_calculate_initial_indicator(self, unique_id, indicator_name, params):
        if not self.timeframe:
            await self.send_json({"error": "Timeframe not set. Please subscribe to a timeframe first."})
            return

        # Determine the required history for the indicator
        indicator_class = self.indicator_service.get_indicator_class(indicator_name)
        if not indicator_class:
            await self.send_json({"error": f"Indicator '{indicator_name}' not found."})
            return
        
        required_history = indicator_class().required_history(**params)
        
        # Fetch enough data to cover the initial chart load and the indicator's required history.
        candles_to_fetch = max(required_history + 50, 500)

        candles = await sync_to_async(self.get_historical_candles)(self.symbol, self.timeframe, candles_to_fetch)
        if "error" in candles:
            await self.send_json({"error": f"Could not fetch historical data for indicator: {candles['error']}"})
            return

        self.historical_data = pd.DataFrame(candles.get('candles', []))
        if self.historical_data.empty:
            await self.send_json({"error": "No historical data returned to calculate indicator."})
            return

        # Store original time format for later, and ensure it's numeric for conversion
        self.historical_data['time'] = pd.to_numeric(self.historical_data['time'], errors='coerce')
        original_time = self.historical_data['time'].copy()

        # Create a temporary dataframe with a proper DatetimeIndex for calculations
        calc_df = self.historical_data.copy()
        # Convert Unix timestamp to a DatetimeIndex first, then localize
        calc_df.index = pd.to_datetime(calc_df['time'], unit='s')
        calc_df.index = calc_df.index.tz_localize('UTC')
        
        # Calculate the indicator.
        indicator_result_df = self.indicator_service.calculate_indicator(calc_df.copy(), indicator_name, params)

        # Determine the integration strategy and find the new columns
        if 'close' in indicator_result_df.columns and len(indicator_result_df) == len(calc_df):
            # Heuristic: If 'close' is present and length matches, it's a full DataFrame (like RSI).
            final_df = indicator_result_df
            new_columns = list(set(final_df.columns) - set(calc_df.columns))
        else:
            # It's likely just the new indicator columns (like Daily Levels). Join them.
            final_df = calc_df.join(indicator_result_df)
            new_columns = list(indicator_result_df.columns)

        if not new_columns:
            await self.send_json({"error": "Indicator calculation returned no new data columns."})
            return

        # Restore the original time column format for sending to the client
        final_df.reset_index(drop=True, inplace=True)
        final_df['time'] = original_time

        # Conditionally format the data based on the number of new columns
        if len(new_columns) == 1:
            # Single-value indicator (e.g., RSI), send data in "wide" format for backward compatibility
            columns_to_send = ['time'] + new_columns
            indicator_data = final_df[columns_to_send].dropna(subset=new_columns).to_dict('records')
            logger.info(f"Sending single-value indicator data for {unique_id} ({indicator_name}): {len(indicator_data)} records.")
            if indicator_data:
                logger.info(f"Sample data point: {indicator_data[0]}")
        else:
            # Multi-value indicator (e.g., Daily Levels), send data in "series" format
            indicator_data = {}
            for col in new_columns:
                series_df = final_df[['time', col]].dropna()
                indicator_data[col] = series_df.rename(columns={col: 'value'}).to_dict('records')
            logger.info(f"Sending multi-value indicator data for {unique_id} ({indicator_name}). Keys: {new_columns}")
            if new_columns and indicator_data.get(new_columns[0]):
                logger.info(f"Sample data point for {new_columns[0]}: {indicator_data[new_columns[0]][0] if indicator_data[new_columns[0]] else 'N/A'}")

        payload = {
            "type": "indicator_data",
            "indicator": indicator_name,
            "unique_id": unique_id,
            "params": params,
            "data": indicator_data,
            "data_keys": new_columns
        }
        
        await self.send_json(payload)

    async def handle_remove_indicator(self, content):
        unique_id = content.get("unique_id")
        if not unique_id:
            await self.send_json({"error": "Unique ID not provided for indicator removal"})
            return

        if unique_id in self.active_indicators:
            indicator_info = self.active_indicators.pop(unique_id) # Use pop to get the value and remove
            indicator_name = indicator_info.get("name", "Unknown")
            logger.info(f"Removed indicator: {indicator_name} with unique_id: {unique_id}")
            await self.send_json({"type": "indicator_removed", "unique_id": unique_id})
        else:
            await self.send_json({"error": f"Indicator with unique_id '{unique_id}' not active"})

    async def handle_unsubscribe(self, content):
        logger.info(f"Received unsubscribe message from client for {self.symbol} for account {self.account_id}")
        if self.platform == "MT5" and self.mt5_client:
            await self.mt5_client.unsubscribe_price(self.symbol)
            if self.timeframe:
                await self.mt5_client.unsubscribe_candles(self.symbol, self.timeframe)
        elif self.price_task:
            self.price_task.cancel()
        await self.send_json({"type": "unsubscribed", "symbol": self.symbol})
        await self.close()

    async def send_price_update(self, price_data):
        """Callback function to send price updates to the client."""
        payload = {
            "type": "live_price",
            "data": price_data
        }
        #logger.info(f"Sending price update for {self.symbol} to client for account {self.account_id}: {json.dumps(payload)}")
        await self.send_json(payload)

    async def send_candle_update(self, candle_data):
        """Callback function to send new candle updates to the client."""
        logger.info(f"Received candle update from MT5 for {self.symbol} {self.timeframe} for account {self.account_id}: {json.dumps(candle_data)}")
        payload = {
            "type": "new_candle",
            "data": candle_data
        }
        logger.info(f"Sending new candle for {self.symbol} {self.timeframe} to client for account {self.account_id}: {json.dumps(payload)}")
        await self.send_json(payload)

    def get_historical_candles(self, symbol, timeframe, count):
        # This method now needs to handle the case where mt5_client is not the old polling client
        # but the new WebSocket-based one. The get_historical_candles method was kept on it.
        if not self.mt5_client:
            return {"error": "MT5 client not initialized"}
        
        # The actual call is synchronous, but it's called from an async context,
        # so it needs to be wrapped if it performs blocking IO.
        # Since it's using `requests`, it's blocking.
        return self.mt5_client.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count
        )

    async def subscribe_ctrader(self):
        subscription_url = "http://localhost:8080/ctrader/symbol/subscribe"
        payload = {
            "access_token": self.ctrader_access_token,
            "ctid_trader_account_id": self.ctid_trader_account_id,
            "symbol": self.symbol.upper()
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(subscription_url, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        await self.send_json({"error": f"Subscription endpoint error: {error_text}"})
                        return False
                    data = await response.json()
                    return True
        except Exception as e:
            await self.send_json({"error": "Error calling subscription endpoint: " + str(e)})
            return False

    async def ctrader_price_stream(self):
        try:
            async with websockets.connect("ws://localhost:9000") as ws:
                greeting = await ws.recv()
                greeting_data = json.loads(greeting)
                if greeting_data.get("status") != "connected":
                    await self.send_json({"error": "Failed to connect to CTRADER live price server"})
                    return

                while True:
                    message = await ws.recv()
                    data = json.loads(message)
                    if data.get("symbol", "").upper() == self.symbol.upper():
                        await self.send_json({
                            "symbol": self.symbol.upper(),
                            "bid": data.get("bid"),
                            "ask": data.get("ask"),
                            "timestamp": data.get("timestamp")
                        })
        except Exception as e:
            await self.send_json({"error": "Error in CTRADER price stream: " + str(e)})
