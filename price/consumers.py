# price/consumers.py
import asyncio
import json
import logging
import pandas as pd
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account, MT5Account, CTraderAccount
from trading_platform.mt5_api_client import MT5APIClient
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

            self.mt5_client = MT5APIClient(
                base_url=settings.MT5_API_BASE_URL,
                account_id=self.mt5_account.account_number,
                password=self.mt5_account.encrypted_password,
                broker_server=self.mt5_account.broker_server
            )
            
            self.price_task = asyncio.create_task(self.price_stream())

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
        if self.price_task:
            self.price_task.cancel()
        logger.info(f"🔻 WebSocket closed for Account: {self.account_id} - {self.symbol}")

    async def receive_json(self, content):
        logger.info(f"Received JSON message: {content}")
        action = content.get("type") or content.get("action")

        if action == "subscribe":
            self.timeframe = content.get("timeframe") or content.get("params", {}).get("timeframe")
            logger.info(f"Subscribed to timeframe: {self.timeframe}")

        elif action == "add_indicator":
            await self.handle_add_indicator(content)

        elif action == "remove_indicator":
            await self.handle_remove_indicator(content)

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

        self.historical_data = pd.DataFrame(candles)
        
        # Calculate the indicator for the historical data
        self.historical_data = self.indicator_service.calculate_indicator(self.historical_data, indicator_name, params)
        
        # Send the historical indicator data to the client
        indicator_data = self.historical_data[['time', f"{indicator_name}_{params.get('length', '')}"]].to_dict('records')
        
        await self.send_json({
            "type": "indicator_data",
            "indicator": indicator_name,
            "unique_id": unique_id, # Include the unique_id
            "params": params,       # Include the params
            "data": indicator_data
        })

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

    async def price_stream(self):
        last_candle = None
        #logger.info("Price stream started")
        # Populate initial historical data if not already populated
        if self.timeframe and self.historical_data.empty:
            candles = await sync_to_async(self.get_historical_candles)(self.symbol, self.timeframe, 200)
            if "error" not in candles:
                self.historical_data = pd.DataFrame(candles)
        try:
            while True:
                try:
                    price_data = await sync_to_async(self.get_mt5_price)(self.symbol)
                    if "error" in price_data:
                        logger.error(f"Error fetching MT5 price for {self.symbol}: {price_data['error']}")
                    else:
                        await self.send_json(price_data)

                    if self.timeframe:
                        #logger.debug(f"Fetching candle data for {self.symbol} with timeframe {self.timeframe}")
                        candle_data = await sync_to_async(self.get_mt5_candle)(self.symbol, self.timeframe)
                        #logger.debug(f"Candle data received: {candle_data}")

                        if "error" not in candle_data:
                            if last_candle:
                                #logger.debug(f"Comparing new candle {candle_data['time']} with last candle {last_candle['time']}")
                             if last_candle and candle_data['time'] > last_candle['time']:
                            
                            
                                #logger.info(f"New candle detected. Closing previous candle: {last_candle}")
                                await self.send_json({'type': 'candle_closed', 'data': last_candle})
                            
                            if not last_candle or candle_data['time'] > last_candle['time'] or candle_data['close'] != last_candle['close']:
                                #logger.info(f"Sending candle update: {candle_data}")
                                await self.send_json({'type': 'candle_update', 'data': candle_data})
                                last_candle = candle_data

                                # Update historical data and recalculate indicators
                                new_candle_df = pd.DataFrame([candle_data])
                                self.historical_data = pd.concat([self.historical_data, new_candle_df], ignore_index=True)
                                
                                # Keep the DataFrame size manageable
                                self.historical_data = self.historical_data.tail(500) 

                                for unique_id, indicator_info in self.active_indicators.items():
                                    name = indicator_info["name"]
                                    params = indicator_info["params"]
                                    
                                    self.historical_data = self.indicator_service.calculate_indicator(self.historical_data, name, params)
                                    latest_indicator_value = self.historical_data.iloc[-1]
                                    
                                    indicator_col_name = f"{name}_{params.get('length', '')}"
                                    
                                    await self.send_json({
                                        "type": "indicator_update",
                                        "indicator": name,
                                        "unique_id": unique_id, # Include the unique_id
                                        "params": params,       # Include the params
                                        "data": {
                                            "time": latest_indicator_value['time'],
                                            "value": latest_indicator_value[indicator_col_name]
                                        }
                                    })
                            else:
                                logger.debug("No new candle data to send.")
                        else:
                            logger.error(f"Error fetching candle data: {candle_data['error']}")
                    else:
                        logger.debug("No timeframe set, skipping candle data fetch.")

                    await asyncio.sleep(1)
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Connection closed, stopping price stream.")
                    break
        except asyncio.CancelledError:
            logger.info(f"MT5 price stream for {self.symbol} cancelled.")
        except Exception as e:
            logger.error(f"Error in MT5 price stream for {self.symbol}: {e}", exc_info=True)

    def get_mt5_price(self, symbol):
        result = self.mt5_client.get_live_price(symbol)
        if "error" in result:
            return {"error": result["error"]}
        return {"symbol": symbol, "bid": result.get("bid"), "ask": result.get("ask")}

    def get_mt5_candle(self, symbol, timeframe):
        result = self.mt5_client.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=1
        )
        if "error" in result:
            return {"error": result["error"]}
        
        candles = result.get("candles", [])
        if candles:
            return candles[0]
        return {"error": "No candle data returned"}

    def get_historical_candles(self, symbol, timeframe, count):
        result = self.mt5_client.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count
        )
        if "error" in result:
            return {"error": result["error"]}
        
        return result.get("candles", [])

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
