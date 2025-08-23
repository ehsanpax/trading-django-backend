# price/consumers.py
import asyncio
import json
import logging
import pandas as pd
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from accounts.models import Account
from django.conf import settings
from datetime import datetime, timedelta
from indicators.services import IndicatorService
from monitoring.services import monitoring_service
from channels.layers import get_channel_layer

# New imports for platform-agnostic service
from connectors.trading_service import TradingService
from connectors.base import PriceData, CandleData

logger = logging.getLogger(__name__)

class PriceConsumer(AsyncJsonWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeframe = None
        self.indicator_service = IndicatorService()
        self.active_indicators = {}
        self.historical_data = pd.DataFrame()
        # TradingService instance
        self._ts: TradingService | None = None
        # Group naming uses uppercase symbol to match backend fanout keys
        self._group_symbol = None
        self._last_tick_ts = None
        self._last_candle_ts = None
        self._price_group = None
        self._candle_group = None
        # Keep callbacks for unsubscribe
        self._price_cb = None
        self._candle_cb = None
        # Track active WS state to avoid sending after close
        self.is_active = False

    async def connect(self):
        self.account_id = self.scope["url_route"]["kwargs"]["account_id"]
        self.symbol = self.scope["url_route"]["kwargs"]["symbol"]
        # Normalize only for Channels group keys; keep original for broker calls
        self._group_symbol = (self.symbol or "").upper()

        await self.accept()
        self.is_active = True

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
            
        # Fetch the account
        self.account = await sync_to_async(Account.objects.filter(id=self.account_id).first)()
        if not self.account:
            await self.send_json({"error": "Invalid account ID"})
            await self.close()
            return

        self.platform = (self.account.platform or "").upper()

        # Join Channels groups to receive backend fanout for price/candles
        price_group = f"prices_{self.account_id}_{self._group_symbol}"
        channel_layer = get_channel_layer()
        if channel_layer:
            await channel_layer.group_add(price_group, self.channel_name)
        self._price_group = price_group

        # Initialize TradingService
        self._ts = TradingService(self.account)

        # Subscribe via TradingService (platform-agnostic)
        async def on_price(pd: PriceData):
            payload = {
                "symbol": pd.symbol,
                "bid": pd.bid,
                "ask": pd.ask,
                "time": getattr(pd, "timestamp", None).timestamp() if getattr(pd, "timestamp", None) else None,
                "timestamp": getattr(pd, "timestamp", None).isoformat() if getattr(pd, "timestamp", None) else None,
            }
            logger.info(f"TS_PATH: price tick {payload}")
            await self.send_price_update(payload)

        self._price_cb = on_price
        try:
            await self._ts.subscribe_price(self.symbol, self._price_cb)
            logger.info(f"TS_PATH: subscribed price for {self.symbol} account={self.account_id}")
        except Exception as e:
            await self.send_json({"error": f"Price subscribe failed: {e}"})
            await self.close()
            return

    async def disconnect(self, close_code):
        # Mark inactive as early as possible
        self.is_active = False
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

        try:
            if self._ts:
                if self._price_cb:
                    try:
                        await self._ts.unsubscribe_price(self.symbol, self._price_cb)
                        logger.info(f"TS_PATH: unsubscribed price for {self.symbol} account={self.account_id}")
                    except Exception as e:
                        logger.debug(f"TS_PATH: unsubscribe price failed: {e}")
                if self.timeframe and self._candle_cb:
                    try:
                        await self._ts.unsubscribe_candles(self.symbol, self.timeframe, self._candle_cb)
                        logger.info(f"TS_PATH: unsubscribed candles {self.symbol}@{self.timeframe}")
                    except Exception as e:
                        logger.debug(f"TS_PATH: unsubscribe candles failed: {e}")
        finally:
            logger.info(f"Price WS disconnected account={self.account_id} symbol={self.symbol}")

    async def receive_json(self, content):
        monitoring_service.update_client_message(self.channel_name, content)
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

                # If changing timeframe, unsubscribe from old one first
                if self.timeframe and self._ts and self._candle_cb:
                    try:
                        await self._ts.unsubscribe_candles(self.symbol, self.timeframe, self._candle_cb)
                    except Exception as e:
                        logger.debug(f"TS_PATH: Unsubscribe old candles failed: {e}")

                self.timeframe = new_timeframe
                if self._ts:
                    async def on_candle(cd: CandleData):
                        data = {
                            "symbol": cd.symbol,
                            "timeframe": cd.timeframe,
                            "open": cd.open,
                            "high": cd.high,
                            "low": cd.low,
                            "close": cd.close,
                            "tick_volume": cd.volume,
                            "time": getattr(cd, "timestamp", None).timestamp() if getattr(cd, "timestamp", None) else None,
                            "timestamp": getattr(cd, "timestamp", None).isoformat() if getattr(cd, "timestamp", None) else None,
                        }
                        logger.debug(f"TS_PATH: candle update {data}")
                        await self.send_candle_update(data)
                    self._candle_cb = on_candle
                    try:
                        await self._ts.subscribe_candles(self.symbol, self.timeframe, self._candle_cb)
                        logger.info(f"TS_PATH: subscribed candles {self.symbol}@{self.timeframe}")
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
        if self._ts:
             try:
                 if self._price_cb:
                     await self._ts.unsubscribe_price(self.symbol, self._price_cb)
                     logger.info(f"TS_PATH: unsubscribe price {self.symbol}")
                 if self.timeframe and self._candle_cb:
                     await self._ts.unsubscribe_candles(self.symbol, self.timeframe, self._candle_cb)
                     logger.info(f"TS_PATH: unsubscribe candles {self.symbol}@{self.timeframe}")
             except Exception as e:
                 logger.debug(f"TS_PATH: unsubscribe failed: {e}")
        
        await self.send_json({"type": "unsubscribed", "symbol": self.symbol})
        await self.close()

    async def send_price_update(self, price_data):
        """Callback function to send price updates to the client."""
        payload = {
            "type": "live_price",
            "data": price_data
        }
        if getattr(self, "close_code", None) is None and self.is_active:
            await self.send_json(payload)
        monitoring_service.update_server_message(self.channel_name, payload)

        try:
            self._last_tick_ts = price_data.get("time") or price_data.get("timestamp")
        except Exception:
            pass

    async def send_candle_update(self, candle_data):
        """Callback function to handle candle updates, calculating indicators on actual close."""
        logger.debug(f"send_candle_update direct path received for account={self.account_id} symbol={self.symbol} tf={self.timeframe} t={candle_data.get('time')}")
        # Always send the raw candle data to the client for the live chart line
        # Coerce any numpy scalar types or objects with .item() to built-in for JSON
        def _py(v):
            try:
                import numpy as _np  # type: ignore
                if isinstance(v, (_np.generic,)):
                    try:
                        return v.item()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                # Many pandas scalars are numpy-backed and support .item()
                if hasattr(v, "item") and callable(getattr(v, "item")):
                    return v.item()
            except Exception:
                pass
            return v
        safe_candle = {k: _py(v) for k, v in (candle_data or {}).items()}
        payload = {"type": "new_candle", "data": safe_candle}
        try:
            if getattr(self, "close_code", None) is None and self.is_active:
                await self.send_json(payload)
        except RuntimeError:
            return
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
                # Align incoming fields to existing columns and fill from previous row for missing ones
                try:
                    prev_row = self.historical_data.iloc[-1].copy()
                    new_row = prev_row.copy()
                    for col in new_candle_df.columns:
                        # Only overwrite known columns; ignore unexpected extras
                        if col in new_row.index:
                            new_row[col] = new_candle_df.iloc[0][col]
                    # Ensure column order and assign
                    self.historical_data.iloc[-1] = new_row
                except Exception:
                    # Fallback: positionally align by reindexing and assign if shapes match
                    aligned = new_candle_df.reindex(columns=self.historical_data.columns)
                    if aligned.shape[1] == self.historical_data.shape[1]:
                        self.historical_data.iloc[-1] = aligned.iloc[0]
                    else:
                        # As a last resort, append to keep stream alive
                        self.historical_data = pd.concat([self.historical_data, aligned], ignore_index=True)

        # --- Step 2: Always recalculate on new data ---
        await self.recalculate_and_send_updates(is_new_candle=is_new_candle)
        
        # --- Step 3: Trim historical data ---
        if len(self.historical_data) > 1000:
            self.historical_data = self.historical_data.iloc[-1000:]

    async def recalculate_and_send_updates(self, is_new_candle):
        """Helper function to calculate indicators and send an update for the latest candle."""
        if self.historical_data.empty:
            return

        # Local helper to coerce numpy/pandas scalars to built-ins
        def _py(v):
            try:
                import numpy as _np  # type: ignore
                if isinstance(v, (_np.generic,)):
                    try:
                        return v.item()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if hasattr(v, "item") and callable(getattr(v, "item")):
                    return v.item()
            except Exception:
                pass
            return v

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
                    try:
                        # Sanitize payload data values
                        payload = {
                            **payload,
                            "data": {k: _py(v) for k, v in payload.get("data", {}).items()}
                        }
                        if getattr(self, "close_code", None) is None and self.is_active:
                            await self.send_json(payload)
                    except RuntimeError:
                        return

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
                try:
                    payload = {
                        **payload,
                        "data": {k: _py(v) for k, v in payload.get("data", {}).items()}
                    }
                    if getattr(self, "close_code", None) is None and self.is_active:
                        await self.send_json(payload)
                except RuntimeError:
                    return

    def get_historical_candles(self, symbol, timeframe, count):
        # Use TradingService to fetch historical candles in unified format
        if not self._ts:
            return {"error": "TradingService not initialized"}
        try:
            # Use sync wrapper to avoid event loop context issues
            raw = self._ts.get_historical_candles_sync(symbol, timeframe, count=count)
            # Adapt to previous payload shape expected by indicator bootstrap
            candles = []
            for c in raw:
                # Convert ISO timestamp to unix seconds; handle trailing 'Z' explicitly
                ts = c.get('timestamp')
                unix_s = None
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(ts)
                    unix_s = int(dt.timestamp())
                except Exception:
                    unix_s = None
                candles.append({
                    'symbol': c.get('symbol'),
                    'timeframe': c.get('timeframe'),
                    'open': c.get('open'),
                    'high': c.get('high'),
                    'low': c.get('low'),
                    'close': c.get('close'),
                    'tick_volume': c.get('volume'),
                    'time': unix_s,
                })
            # If too few candles returned, fallback to a time-range fetch
            if len(candles) < 50:
                try:
                    tf_map = {
                        'M1': 60, 'M5': 300, 'M15': 900, 'M30': 1800,
                        'H1': 3600, 'H4': 14400, 'D1': 86400
                    }
                    sec = tf_map.get(str(timeframe).upper(), 300)
                    end_dt = datetime.utcnow()
                    start_dt = end_dt - pd.Timedelta(seconds=sec * max(50, int(count or 500)))
                    raw = self._ts.get_historical_candles_sync(symbol, timeframe, start_time=start_dt, end_time=end_dt)
                    candles = []
                    for c in raw:
                        ts = c.get('timestamp')
                        unix_s = None
                        try:
                            if isinstance(ts, str):
                                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                            else:
                                dt = datetime.fromisoformat(ts)
                            unix_s = int(dt.timestamp())
                        except Exception:
                            unix_s = None
                        candles.append({
                            'symbol': c.get('symbol'),
                            'timeframe': c.get('timeframe'),
                            'open': c.get('open'),
                            'high': c.get('high'),
                            'low': c.get('low'),
                            'close': c.get('close'),
                            'tick_volume': c.get('volume'),
                            'time': unix_s,
                        })
                except Exception:
                    pass
            # Optional: log count for diagnostics
            try:
                logger.info(f"HIST_BOOTSTRAP count={len(candles)} account={self.account_id} symbol={symbol} tf={timeframe}")
            except Exception:
                pass
            return {"candles": candles}
        except Exception as e:
            return {"error": str(e)}
        finally:
            pass

    # Group message handlers used by Channels
    async def price_tick(self, event):
        """Channels group message: {'type': 'price_tick', 'price': {...}}"""
        price = event.get("price") or {}
        await self.send_price_update(price)

    async def candle_update(self, event):
        """Channels group message: {'type': 'candle_update', 'candle': {...}}"""
        candle = event.get("candle") or {}
        await self.send_candle_update(candle)
