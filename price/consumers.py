# price/consumers.py
import asyncio
import json
import logging
import pandas as pd
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account, MT5Account, CTraderAccount
from trading_platform.mt5_api_client import (
    MT5APIClient,
    connection_manager,
    mt5_ensure_ready,
    mt5_subscribe_price,
    mt5_unsubscribe_price,
    mt5_subscribe_candles,
    mt5_unsubscribe_candles,
    mt5_subscriptions_status,
)
from django.conf import settings
import websockets, aiohttp
from datetime import datetime, timedelta
from indicators.services import IndicatorService
from monitoring.services import monitoring_service
<<<<<<< Updated upstream
from channels.layers import get_channel_layer
=======
>>>>>>> Stashed changes

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
        # --- MT5 headless orchestration args & state ---
        self._mt5_args = None
        self._mt5_price_subscribed = False
        # Group naming uses uppercase symbol to match backend fanout keys
        self._group_symbol = None
        self._last_tick_ts = None
        self._last_candle_ts = None

    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]
        # Normalize only for Channels group keys; keep original for MT5 API calls
        self._group_symbol = (self.symbol or "").upper()

        await self.accept()
<<<<<<< Updated upstream
        #logger.info(f"Price WS connected account={self.account_id} symbol={self.symbol}")
=======
>>>>>>> Stashed changes

        monitoring_service.register_connection(
            self.channel_name,
            self.scope.get("user"),
            self.account_id,
            "price",
            {"symbol": self.symbol}
        )
        
        if not self.account_id:
            await self.send_json({"error": "Account ID not provided"})
            await self.close()
            return
            
        # Fetch the account from the database using async ORM (via sync_to_async)
        self.account = await sync_to_async(Account.objects.filter(id=self.account_id).first)()
        if not self.account:
            await self.send_json({"error": "Invalid account ID"})
            await self.close()
            return

        self.platform = self.account.platform.upper()

        # Join Channels groups to receive backend fanout for price/candles
        price_group = f"prices_{self.account_id}_{self._group_symbol}"
        channel_layer = get_channel_layer()
        if channel_layer:
            await channel_layer.group_add(price_group, self.channel_name)
            #logger.info(f"Joined price group: {price_group}")
        self._price_group = price_group
        self._candle_group = None

        if self.platform == "MT5":
            # Prepare MT5 args and ensure headless poller is running
            self.mt5_account = await sync_to_async(MT5Account.objects.filter(account_id=self.account.id).first)()
            if not self.mt5_account:
                await self.send_json({"error": "No MT5 account found"})
                await self.close()
                return
            self._mt5_args = {
                "base_url": settings.MT5_API_BASE_URL,
                "account_id": self.mt5_account.account_number,
                "password": self.mt5_account.encrypted_password,
                "broker_server": self.mt5_account.broker_server,
                "internal_account_id": str(self.account.id),
            }
            try:
                # Ensure MT5 headless is ready
                await mt5_ensure_ready(**self._mt5_args)
                # Keep a client for REST endpoints like historical candles
                self.mt5_client = await connection_manager.get_client(**self._mt5_args)
                # Subscribe to price ticks for this symbol (headless)
                refs = await mt5_subscribe_price(**self._mt5_args, symbol=self.symbol)
                self._mt5_price_subscribed = True
                logger.info(f"Headless MT5 price subscribe requested for {self.symbol} (account={self.account_id}) refs={refs}")
                try:
                    status = await mt5_subscriptions_status(**self._mt5_args)
                    logger.info(f"MT5 headless status after connect price subscribe: {status}")
                except Exception as e:
                    logger.debug(f"mt5_subscriptions_status failed: {e}")
            except Exception as e:
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
<<<<<<< Updated upstream
        # Leave Channels groups
        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                if getattr(self, "_price_group", None):
                    await channel_layer.group_discard(self._price_group, self.channel_name)
                    logger.info(f"Left price group: {self._price_group}")
                if getattr(self, "_candle_group", None):
                    await channel_layer.group_discard(self._candle_group, self.channel_name)
                    logger.info(f"Left candle group: {self._candle_group}")
        except Exception:
            pass
        monitoring_service.unregister_connection(self.channel_name)
        if self.platform == "MT5" and self._mt5_args:
            try:
                if self._mt5_price_subscribed:
                    refs = await mt5_unsubscribe_price(**self._mt5_args, symbol=self.symbol)
                    logger.info(f"MT5 headless unsubscribe price on disconnect {self.symbol} refs={refs}")
                if self.timeframe:
                    refs_c = await mt5_unsubscribe_candles(**self._mt5_args, symbol=self.symbol, timeframe=self.timeframe)
                    logger.info(f"MT5 headless unsubscribe candles on disconnect {self.symbol}@{self.timeframe} refs={refs_c}")
                try:
                    status = await mt5_subscriptions_status(**self._mt5_args)
                    logger.info(f"MT5 headless status after disconnect: {status}")
                except Exception as e:
                    logger.debug(f"mt5_subscriptions_status failed: {e}")
            except Exception as e:
                logger.debug(f"MT5 headless unsubscribe on disconnect failed: {e}")
=======
        monitoring_service.unregister_connection(self.channel_name)
        #logger.info(f"🔻 WebSocket disconnected for Account: {self.account_id} - {self.symbol}")
        if self.platform == "MT5" and self.mt5_client:
            self.mt5_client.unregister_price_listener(self.symbol, self.send_price_update)
            if self.timeframe: # If we were subscribed to candles, unregister
                self.mt5_client.unregister_candle_listener(self.symbol, self.timeframe, self.send_candle_update)
>>>>>>> Stashed changes
        elif self.price_task:
            self.price_task.cancel()
        logger.info(f"Price WS disconnected account={self.account_id} symbol={self.symbol}")

    async def receive_json(self, content):
        monitoring_service.update_client_message(self.channel_name, content)
<<<<<<< Updated upstream
=======
        #logger.info(f"Received message from client for account {self.account_id} - {self.symbol}: {json.dumps(content)}")
>>>>>>> Stashed changes
        action = content.get("type") or content.get("action")
        logger.info(f"Client message action={action} account={self.account_id} symbol={self.symbol} payload={content}")

        if action == "subscribe":
            new_timeframe = content.get("timeframe") or content.get("params", {}).get("timeframe")
            logger.info(f"Subscribe request for candles account={self.account_id} symbol={self.symbol} timeframe={new_timeframe}")
            if new_timeframe and new_timeframe != self.timeframe:
                # join candle group for this timeframe
                channel_layer = get_channel_layer()
                if self._candle_group and channel_layer:
                    await channel_layer.group_discard(self._candle_group, self.channel_name)
                    logger.info(f"Discarded previous candle group: {self._candle_group}")
                self._candle_group = f"candles_{self.account_id}_{self._group_symbol}_{new_timeframe}"
                if channel_layer:
                    await channel_layer.group_add(self._candle_group, self.channel_name)
                    logger.info(f"Joined candle group: {self._candle_group}")

                # If changing timeframe, unsubscribe from old one first (headless)
                if self.timeframe and self._mt5_args:
                    logger.info(f"Headless MT5 unsubscribe candles {self.symbol}@{self.timeframe}")
                    try:
                        await mt5_unsubscribe_candles(**self._mt5_args, symbol=self.symbol, timeframe=self.timeframe)
                    except Exception as e:
                        logger.debug(f"Unsubscribe old candles failed: {e}")

                self.timeframe = new_timeframe
                if self._mt5_args:
                    try:
                        count = await mt5_subscribe_candles(**self._mt5_args, symbol=self.symbol, timeframe=self.timeframe)
                        logger.info(f"Headless MT5 subscribe candles {self.symbol}@{self.timeframe} (account={self.account_id}) refs={count}")
                        try:
                            status = await mt5_subscriptions_status(**self._mt5_args)
                            logger.info(f"MT5 headless status after subscribe candles: {status}")
                        except Exception as e:
                            logger.debug(f"mt5_subscriptions_status failed: {e}")
                    except Exception as e:
                        await self.send_json({"error": f"Failed to subscribe candles: {e}"})

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

        self.active_indicators[unique_id] = {"name": indicator_name, "params": params} # Store by unique_id
        
        # Fetch historical data to calculate the indicator
        await self.fetch_and_calculate_initial_indicator(unique_id, indicator_name, params)

    async def fetch_and_calculate_initial_indicator(self, unique_id, indicator_name, params):
        if not self.timeframe:
            await self.send_json({"error": "Timeframe not set. Please subscribe to a timeframe first."})
            return

        # With the new IndicatorInterface, we don't have a required_history method.
        # We'll fetch a fixed, generous amount of data and let the indicator compute method handle it.
        candles_to_fetch = 500

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
            columns_to_send = ['time'] + new_columns
            indicator_data = final_df[columns_to_send].dropna(subset=new_columns).to_dict('records')
            if indicator_data:
                logger.info(f"Indicator {indicator_name} initial data points={len(indicator_data)} first={indicator_data[0]}")
        else:
            indicator_data = {}
            for col in new_columns:
                series_df = final_df[['time', col]].dropna()
                indicator_data[col] = series_df.rename(columns={col: 'value'}).to_dict('records')
            if new_columns and indicator_data.get(new_columns[0]):
                logger.info(f"Indicator {indicator_name} initial series keys={new_columns}")

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
            await self.send_json({"type": "indicator_removed", "unique_id": unique_id})
        else:
            await self.send_json({"error": f"Indicator with unique_id '{unique_id}' not active"})

    async def handle_unsubscribe(self, content):
        logger.info(f"Client unsubscribe for account={self.account_id} symbol={self.symbol} timeframe={self.timeframe}")
        if self.platform == "MT5" and self._mt5_args:
            try:
                if self._mt5_price_subscribed:
                    count = await mt5_unsubscribe_price(**self._mt5_args, symbol=self.symbol)
                    logger.info(f"Headless MT5 unsubscribe price {self.symbol} refs={count}")
                if self.timeframe:
                    count_c = await mt5_unsubscribe_candles(**self._mt5_args, symbol=self.symbol, timeframe=self.timeframe)
                    logger.info(f"Headless MT5 unsubscribe candles {self.symbol}@{self.timeframe} refs={count_c}")
                try:
                    status = await mt5_subscriptions_status(**self._mt5_args)
                    logger.info(f"MT5 headless status after unsubscribe: {status}")
                except Exception as e:
                    logger.debug(f"mt5_subscriptions_status failed: {e}")
            except Exception as e:
                logger.debug(f"Headless MT5 unsubscribe failed: {e}")
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
        await self.send_json(payload)
        monitoring_service.update_server_message(self.channel_name, payload)
<<<<<<< Updated upstream

        try:
            self._last_tick_ts = price_data.get("time") or price_data.get("timestamp")
        except Exception:
            pass
=======
>>>>>>> Stashed changes

    async def send_candle_update(self, candle_data):
        """Callback function to handle candle updates, calculating indicators on actual close."""
        logger.debug(f"send_candle_update direct path received for account={self.account_id} symbol={self.symbol} tf={self.timeframe} t={candle_data.get('time')}")
        # Always send the raw candle data to the client for the live chart line
        payload = {"type": "new_candle", "data": candle_data}
        await self.send_json(payload)
        monitoring_service.update_server_message(self.channel_name, payload)

        if not self.active_indicators:
            return

        # --- Step 1: Always update the historical data first ---
        new_candle_df = pd.DataFrame([candle_data])
        new_candle_df['time'] = pd.to_numeric(new_candle_df['time'], errors='coerce')
        new_time = new_candle_df['time'].iloc[0]

        is_new_candle = False
        if self.historical_data.empty:
            self.historical_data = new_candle_df
        else:
            last_time = self.historical_data['time'].iloc[-1]
            if new_time > last_time:
                is_new_candle = True
                # Append the new, forming candle
                self.historical_data = pd.concat([self.historical_data, new_candle_df], ignore_index=True)
            else:
                # Update the currently forming candle
                self.historical_data.iloc[-1] = new_candle_df.iloc[0]

        # --- Step 2: Always recalculate on new data ---
        await self.recalculate_and_send_updates(is_new_candle=is_new_candle)
        
        # --- Step 3: Trim historical data ---
        if len(self.historical_data) > 1000:
            self.historical_data = self.historical_data.iloc[-1000:]

    async def recalculate_and_send_updates(self, is_new_candle):
        """Helper function to calculate indicators and send an update for the latest candle."""
        if self.historical_data.empty:
            return

        # The entire historical data, including the first tick of the new candle, is needed for accurate calculation.
        calc_df = self.historical_data.copy()
        calc_df.index = pd.to_datetime(calc_df['time'], unit='s')
        calc_df.index = calc_df.index.tz_localize('UTC')

        for unique_id, indicator_info in self.active_indicators.items():
            indicator_name = indicator_info["name"]
            params = indicator_info["params"]

            indicator_result_df = self.indicator_service.calculate_indicator(calc_df.copy(), indicator_name, params)

            # Integration logic...
            if 'close' in indicator_result_df.columns and len(indicator_result_df) == len(calc_df):
                final_df = indicator_result_df
                new_columns = list(set(final_df.columns) - set(calc_df.columns))
            else:
                final_df = calc_df.join(indicator_result_df)
                new_columns = list(indicator_result_df.columns)

            if not new_columns:
                continue

            # Preserve the original time column, which gets dropped by the indicator calculation.
            original_times = calc_df['time'].reset_index(drop=True)
            final_df.reset_index(drop=True, inplace=True)
            final_df['time'] = original_times

            # The target is always the last row, which represents the currently forming candle.
            if len(final_df) < 1:
                continue
            
            # If it's a new candle, we send the value for the previously closed candle first
            if is_new_candle and len(final_df) >= 2:
                closed_candle_point = final_df.iloc[-2]
                if len(new_columns) == 1:
                    update_data = closed_candle_point[['time'] + new_columns].dropna().to_dict()
                else:
                    update_data = {'time': closed_candle_point['time']}
                    for col in new_columns:
                        if pd.notna(closed_candle_point[col]):
                            update_data[col] = closed_candle_point[col]
                
                if len(update_data) > 1:
                    payload = {
                        "type": "indicator_update",
                        "indicator": indicator_name,
                        "unique_id": unique_id,
                        "data": update_data,
                        "data_keys": new_columns
                    }
                    await self.send_json(payload)

            # Now, send the update for the currently forming candle
            latest_point = final_df.iloc[-1]
            if len(new_columns) == 1:
                update_data = latest_point[['time'] + new_columns].dropna().to_dict()
            else:
                update_data = {'time': latest_point['time']}
                for col in new_columns:
                    if pd.notna(latest_point[col]):
                        update_data[col] = latest_point[col]
            
            if len(update_data) > 1:
                payload = {
                    "type": "indicator_update",
                    "indicator": indicator_name,
                    "unique_id": unique_id,
                    "data": update_data,
                    "data_keys": new_columns
                }
                await self.send_json(payload)

    def get_historical_candles(self, symbol, timeframe, count):
        if not self.mt5_client:
            return {"error": "MT5 client not initialized"}
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

    # Group message handlers used by Channels
    async def price_tick(self, event):
        # event: {"type": "price_tick", "price": {...}}
        logger.debug(f"Channels price_tick received for account={self.account_id} symbol={self.symbol}")
        price = event.get("price", {})
        await self.send_price_update(price)

    async def candle_update(self, event):
        # event: {"type": "candle_update", "candle": {...}}
        logger.debug(f"Channels candle_update received for account={self.account_id} symbol={self.symbol} tf={self.timeframe}")
        candle = event.get("candle", {})
        await self.send_candle_update(candle)
