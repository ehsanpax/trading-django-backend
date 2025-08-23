# connectors/trading_service.py
"""
Platform-agnostic trading service that uses standardized connectors.
This service abstracts all platform-specific logic and provides a clean
interface for core business logic.

All platform-specific operations are delegated to the connector implementations,
making it easy to add new platforms without changing business logic.
"""

import logging
from typing import Dict, Any, Optional, List, Callable
from decimal import Decimal
from datetime import datetime
import asyncio  # added for sync wrappers

from accounts.models import Account
from .factory import (
    get_connector,  # sync factory for sync wrappers
    get_connector_async,  # async-safe factory
)
from .base import (
    TradingPlatformConnector, 
    TradeRequest, 
    PositionInfo, 
    AccountInfo,
    ConnectorError,
    PriceData,
    CandleData,
)
from trades.exceptions import TradeValidationError, BrokerAPIError

logger = logging.getLogger(__name__)


class TradingService:
    """
    Platform-agnostic trading service that provides consistent interface
    for all trading operations regardless of the underlying platform.
    """

    def __init__(self, account: Account):
        """
        Initialize trading service for a specific account.
        
        Args:
            account: Account instance with platform information
        """
        self.account = account
        self._connector: Optional[TradingPlatformConnector] = None
        # Track subscriptions to help with clean unsubscription in some connectors
        self._price_callbacks: Dict[str, List[Callable[[PriceData], None]]] = {}
        self._candle_callbacks: Dict[str, Dict[str, List[Callable[[CandleData], None]]]] = {}

    async def _get_connector(self) -> TradingPlatformConnector:
        """Get or create connector instance for the account without forcing a connection."""
        if self._connector is None:
            # Use async-safe factory to avoid sync ORM in async contexts
            self._connector = await get_connector_async(self.account)
            # Do not auto-connect here; many read-only ops use REST and don't require a session
        return self._connector

    # --- Sync wrappers for snapshot usage in sync views ---
    def _get_connector_sync(self) -> TradingPlatformConnector:
        if self._connector is None:
            self._connector = get_connector(self.account)
        return self._connector

    def _run_sync(self, coro):
        """Run a simple coroutine in an isolated loop (no DB/ORM inside the coro)."""
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            if loop is not None:
                loop.close()
                asyncio.set_event_loop(None)

    def get_account_info_sync(self) -> AccountInfo:
        try:
            connector = self._get_connector_sync()
            return self._run_sync(connector.get_account_info())
        except ConnectorError as e:
            logger.error(f"Failed to get account info: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def get_open_positions_sync(self) -> List[PositionInfo]:
        try:
            connector = self._get_connector_sync()
            return self._run_sync(connector.get_open_positions())
        except ConnectorError as e:
            logger.error(f"Failed to get open positions: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def place_trade(
        self,
        symbol: str,
        lot_size: float,
        direction: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_type: str = "MARKET",
    limit_price: Optional[float] = None,
    sl_distance: Optional[float] = None,
    tp_distance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place a trade on any supported platform.
        
        Args:
            symbol: Trading instrument symbol
            lot_size: Size of the trade
            direction: "BUY" or "SELL"
            stop_loss: Stop loss price (optional)
            take_profit: Take profit price (optional)
            order_type: "MARKET" or "LIMIT"
            limit_price: Limit price for limit orders
            
        Returns:
            Dict containing trade execution result
        """
        try:
            connector = await self._get_connector()
            
            trade_request = TradeRequest(
                symbol=symbol,
                lot_size=lot_size,
                direction=direction,
                stop_loss=stop_loss,
                take_profit=take_profit,
                order_type=order_type,
                limit_price=limit_price,
                sl_distance=sl_distance,
                tp_distance=tp_distance,
            )
            
            result = await connector.place_trade(trade_request)
            logger.info(f"Trade placed successfully on {connector.get_platform_name()}: {result}")
            return result
            
        except ConnectorError as e:
            logger.error(f"Failed to place trade: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def place_trade_sync(
        self,
        symbol: str,
        lot_size: float,
        direction: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_type: str = "MARKET",
    limit_price: Optional[float] = None,
    sl_distance: Optional[float] = None,
    tp_distance: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Sync wrapper for placing a trade (safe: network I/O only).
        Uses sync connector path to avoid async ORM in event loop.
        """
        try:
            connector = self._get_connector_sync()
            trade_request = TradeRequest(
                symbol=symbol,
                lot_size=lot_size,
                direction=direction,
                stop_loss=stop_loss,
                take_profit=take_profit,
                order_type=order_type,
                limit_price=limit_price,
                sl_distance=sl_distance,
                tp_distance=tp_distance,
            )
            return self._run_sync(connector.place_trade(trade_request))
        except ConnectorError as e:
            logger.error(f"Failed to place trade (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def close_position(self, position_id: str, volume: float, symbol: str) -> Dict[str, Any]:
        """
        Close a position on any supported platform.
        
        Args:
            position_id: Platform-specific position identifier
            volume: Volume to close
            symbol: Trading instrument symbol
            
        Returns:
            Dict containing closure result
        """
        try:
            connector = await self._get_connector()
            result = await connector.close_position(position_id, volume, symbol)
            logger.info(f"Position closed successfully on {connector.get_platform_name()}: {result}")
            return result
            
        except ConnectorError as e:
            logger.error(f"Failed to close position: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def close_position_sync(self, position_id: str, volume: float, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for closing a position.
        Uses sync connector path and isolated event loop to avoid ORM in loop.
        """
        try:
            connector = self._get_connector_sync()
            return self._run_sync(connector.close_position(position_id, volume, symbol))
        except ConnectorError as e:
            logger.error(f"Failed to close position (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def modify_position_protection(
        self,
        position_id: str,
        symbol: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Modify position protection levels on any supported platform.
        
        Args:
            position_id: Platform-specific position identifier
            symbol: Trading instrument symbol
            stop_loss: New stop loss level (optional)
            take_profit: New take profit level (optional)
            
        Returns:
            Dict containing modification result
        """
        try:
            connector = await self._get_connector()
            result = await connector.modify_position_protection(
                position_id, symbol, stop_loss, take_profit
            )
            logger.info(f"Position protection modified on {connector.get_platform_name()}: {result}")
            return result
            
        except ConnectorError as e:
            logger.error(f"Failed to modify position protection: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def modify_position_protection_sync(
        self,
        position_id: str,
        symbol: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Sync wrapper for modifying protection levels (SL/TP).
        Uses sync connector path and isolated event loop.
        """
        try:
            connector = self._get_connector_sync()
            return self._run_sync(
                connector.modify_position_protection(position_id, symbol, stop_loss, take_profit)
            )
        except ConnectorError as e:
            logger.error(f"Failed to modify position protection (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def get_position_details(self, position_id: str) -> PositionInfo:
        """
        Get detailed information about a specific position.
        
        Args:
            position_id: Platform-specific position identifier
            
        Returns:
            PositionInfo with standardized position data
        """
        try:
            connector = await self._get_connector()
            return await connector.get_position_details(position_id)
            
        except ConnectorError as e:
            logger.error(f"Failed to get position details: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def get_position_details_sync(self, position_id: str):
        """Sync wrapper for get_position_details using sync connector path.
        Avoids async factory to prevent CurrentThreadExecutor errors.
        """
        try:
            connector = self._get_connector_sync()
            return self._run_sync(connector.get_position_details(position_id))
        except ConnectorError as e:
            logger.error(f"Failed to get position details (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def get_open_positions(self) -> List[PositionInfo]:
        """
        Get all open positions for the account.
        
        Returns:
            List of PositionInfo objects
        """
        try:
            connector = await self._get_connector()
            return await connector.get_open_positions()
            
        except ConnectorError as e:
            logger.error(f"Failed to get open positions: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def get_account_info(self) -> AccountInfo:
        """
        Get current account information.
        
        Returns:
            AccountInfo with standardized account data
        """
        try:
            connector = await self._get_connector()
            return await connector.get_account_info()
            
        except ConnectorError as e:
            logger.error(f"Failed to get account info: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel a pending order.
        
        Args:
            order_id: Platform-specific order identifier
            
        Returns:
            Dict containing cancellation result
        """
        try:
            connector = await self._get_connector()
            result = await connector.cancel_order(order_id)
            logger.info(f"Order cancelled on {connector.get_platform_name()}: {result}")
            return result
            
        except ConnectorError as e:
            logger.error(f"Failed to cancel order: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def cancel_order_sync(self, order_id: str) -> Dict[str, Any]:
        """Sync wrapper for cancelling a pending order.
        Uses sync connector path and isolated event loop similar to other sync methods.
        """
        try:
            connector = self._get_connector_sync()
            return self._run_sync(connector.cancel_order(order_id))
        except ConnectorError as e:
            logger.error(f"Failed to cancel order (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def get_live_price(self, symbol: str) -> Dict[str, Any]:
        """
        Get current live price for a symbol.
        
        Args:
            symbol: Trading instrument symbol
            
        Returns:
            Dict with price data (bid, ask, timestamp)
        """
        try:
            connector = await self._get_connector()
            price_data = await connector.get_live_price(symbol)
            return {
                'symbol': price_data.symbol,
                'bid': price_data.bid,
                'ask': price_data.ask,
                'timestamp': price_data.timestamp.isoformat()
            }
            
        except ConnectorError as e:
            logger.error(f"Failed to get live price: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def get_live_price_sync(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper for getting current live price for a symbol.
        Uses sync connector path and isolated event loop similar to other sync methods.
        Returns a dict with bid/ask/timestamp keys.
        """
        try:
            connector = self._get_connector_sync()
            price_data = self._run_sync(connector.get_live_price(symbol))
            return {
                'symbol': price_data.symbol,
                'bid': price_data.bid,
                'ask': price_data.ask,
                'timestamp': price_data.timestamp.isoformat()
            }
        except ConnectorError as e:
            logger.error(f"Failed to get live price (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        count: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get historical candle data.
        
        Args:
            symbol: Trading instrument symbol
            timeframe: Timeframe (e.g., "M1", "H1", "D1")
            count: Number of candles (alternative to time range)
            start_time: Start time for data range
            end_time: End time for data range
            
        Returns:
            List of candle data dictionaries
        """
        try:
            connector = await self._get_connector()
            candles = await connector.get_historical_candles(
                symbol, timeframe, count, start_time, end_time
            )
            
            return [
                {
                    'symbol': candle.symbol,
                    'timeframe': candle.timeframe,
                    'open': candle.open,
                    'high': candle.high,
                    'low': candle.low,
                    'close': candle.close,
                    'volume': candle.volume,
                    'timestamp': candle.timestamp.isoformat()
                }
                for candle in candles
            ]
            
        except ConnectorError as e:
            logger.error(f"Failed to get historical candles: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def get_historical_candles_sync(
        self,
        symbol: str,
        timeframe: str,
        count: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Sync wrapper for historical candles, matching the async return shape.
        """
        try:
            connector = self._get_connector_sync()
            candles = self._run_sync(
                connector.get_historical_candles(symbol, timeframe, count, start_time, end_time)
            )
            return [
                {
                    'symbol': c.symbol,
                    'timeframe': c.timeframe,
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': c.volume,
                    'timestamp': c.timestamp.isoformat(),
                }
                for c in candles
            ]
        except ConnectorError as e:
            logger.error(f"Failed to get historical candles (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """
        Get symbol information (pip size, lot size, etc.).
        
        Args:
            symbol: Trading instrument symbol
            
        Returns:
            Dict containing symbol information
        """
        try:
            connector = await self._get_connector()
            return await connector.get_symbol_info(symbol)
            
        except ConnectorError as e:
            logger.error(f"Failed to get symbol info: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def get_symbol_info_sync(self, symbol: str) -> Dict[str, Any]:
        """Sync wrapper to fetch symbol info via the connector."""
        try:
            connector = self._get_connector_sync()
            return self._run_sync(connector.get_symbol_info(symbol))
        except ConnectorError as e:
            logger.error(f"Failed to get symbol info (sync): {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    # --- Optional helpers: pending orders and trade sync data (platform-specific support) ---
    def get_pending_orders_sync(self) -> List[Dict[str, Any]]:
        """Fetch pending orders if the connector supports it; else return empty list."""
        connector = self._get_connector_sync()
        if hasattr(connector, 'get_pending_orders'):
            try:
                return self._run_sync(connector.get_pending_orders())
            except ConnectorError as e:
                logger.error(f"Failed to get pending orders (sync): {e}")
                raise BrokerAPIError(f"Trading platform error: {e}")
        return []

    def fetch_trade_sync_data_sync(self, position_id: str, symbol: str) -> Dict[str, Any]:
        """Fetch platform trade sync data if supported by the connector."""
        connector = self._get_connector_sync()
        if hasattr(connector, 'fetch_trade_sync_data'):
            try:
                return self._run_sync(connector.fetch_trade_sync_data(position_id, symbol))
            except ConnectorError as e:
                logger.error(f"Failed to fetch trade sync data (sync): {e}")
                raise BrokerAPIError(f"Trading platform error: {e}")
        raise BrokerAPIError("Trade sync not supported by this connector")

    # --- Live data subscriptions via connectors ---
    async def subscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        try:
            connector = await self._get_connector()
            await connector.subscribe_price(symbol, callback)
            self._price_callbacks.setdefault(symbol, []).append(callback)
            logger.info(f"TS subscribe_price on {connector.get_platform_name()} symbol={symbol}")
        except ConnectorError as e:
            logger.error(f"Failed to subscribe price: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def unsubscribe_price(self, symbol: str, callback: Optional[Callable[[PriceData], None]] = None) -> None:
        try:
            connector = await self._get_connector()
            # Pass-through callback for connectors that need it
            cb = callback
            if cb is None and symbol in self._price_callbacks and self._price_callbacks[symbol]:
                cb = self._price_callbacks[symbol][-1]
            await connector.unsubscribe_price(symbol, cb)
            if symbol in self._price_callbacks and cb in self._price_callbacks[symbol]:
                self._price_callbacks[symbol].remove(cb)
            logger.info(f"TS unsubscribe_price on {connector.get_platform_name()} symbol={symbol}")
        except ConnectorError as e:
            logger.error(f"Failed to unsubscribe price: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def subscribe_candles(self, symbol: str, timeframe: str, callback: Callable[[CandleData], None]) -> None:
        try:
            connector = await self._get_connector()
            await connector.subscribe_candles(symbol, timeframe, callback)
            self._candle_callbacks.setdefault(symbol, {}).setdefault(timeframe, []).append(callback)
            logger.info(f"TS subscribe_candles on {connector.get_platform_name()} {symbol}@{timeframe}")
        except ConnectorError as e:
            logger.error(f"Failed to subscribe candles: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    async def unsubscribe_candles(self, symbol: str, timeframe: str, callback: Optional[Callable[[CandleData], None]] = None) -> None:
        try:
            connector = await self._get_connector()
            cb = callback
            if cb is None:
                cbs = self._candle_callbacks.get(symbol, {}).get(timeframe, [])
                if cbs:
                    cb = cbs[-1]
            await connector.unsubscribe_candles(symbol, timeframe, cb)
            if symbol in self._candle_callbacks and timeframe in self._candle_callbacks[symbol]:
                if cb in self._candle_callbacks[symbol][timeframe]:
                    self._candle_callbacks[symbol][timeframe].remove(cb)
            logger.info(f"TS unsubscribe_candles on {connector.get_platform_name()} {symbol}@{timeframe}")
        except ConnectorError as e:
            logger.error(f"Failed to unsubscribe candles: {e}")
            raise BrokerAPIError(f"Trading platform error: {e}")

    def get_platform_name(self) -> str:
        """Get the name of the trading platform for this account"""
        return self.account.platform

    def is_platform_supported(self) -> bool:
        """Check if the account's platform is supported"""
        try:
            get_connector(self.account)
            return True
        except ValueError:
            return False

    async def disconnect(self):
        """Disconnect from the trading platform"""
        if self._connector:
            try:
                await self._connector.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._connector = None


# Convenience function for backward compatibility
async def get_trading_service(account: Account) -> TradingService:
    """
    Get a trading service instance for an account.
    
    Args:
        account: Account instance
        
    Returns:
        TradingService configured for the account's platform
    """
    return TradingService(account)
