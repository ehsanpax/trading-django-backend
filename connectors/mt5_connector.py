# connectors/mt5_connector.py
"""
MT5 connector that implements the standardized TradingPlatformConnector interface.
Wraps the existing MT5APIClient to provide consistent API.
"""

import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from decimal import Decimal

from .base import (
    TradingPlatformConnector, 
    TradeRequest, 
    PositionInfo, 
    AccountInfo, 
    PriceData, 
    CandleData,
    ConnectionError,
    AuthenticationError
)
from trading_platform.mt5_api_client import MT5APIClient, mt5_subscribe_price, mt5_unsubscribe_price, mt5_subscribe_candles, mt5_unsubscribe_candles
from trades.exceptions import BrokerAPIError, BrokerConnectionError

logger = logging.getLogger(__name__)


class MT5Connector(TradingPlatformConnector):
    """
    MT5 implementation of the TradingPlatformConnector interface.
    Wraps the existing MT5APIClient to provide standardized interface.
    """

    def __init__(self, account_credentials: Dict[str, Any]):
        """
        Initialize MT5 connector with credentials.
        
        Args:
            account_credentials: Dict containing:
                - base_url: MT5 API base URL
                - account_id: MT5 account number
                - password: MT5 account password
                - broker_server: MT5 broker server
                - internal_account_id: Internal account ID
        """
        required_fields = ['base_url', 'account_id', 'password', 'broker_server', 'internal_account_id']
        missing_fields = [field for field in required_fields if field not in account_credentials]
        if missing_fields:
            raise ValueError(f"Missing required credentials: {missing_fields}")

        # Keep raw credentials for headless orchestrator calls
        self._creds = {
            'base_url': account_credentials['base_url'],
            'account_id': account_credentials['account_id'],
            'password': account_credentials['password'],
            'broker_server': account_credentials['broker_server'],
            'internal_account_id': account_credentials['internal_account_id'],
        }

        self._client = MT5APIClient(
            base_url=account_credentials['base_url'],
            account_id=account_credentials['account_id'],
            password=account_credentials['password'],
            broker_server=account_credentials['broker_server'],
            internal_account_id=account_credentials['internal_account_id']
        )
        self._connected = False

    async def connect(self) -> Dict[str, Any]:
        """Establish connection to MT5 platform"""
        try:
            result = self._client.connect()
            self._connected = True
            return result
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to connect to MT5: {e}")

    async def disconnect(self) -> Dict[str, Any]:
        """Disconnect from MT5 platform"""
        try:
            result = self._client.delete_instance()
            self._connected = False
            return result
        except Exception as e:
            logger.warning(f"Error during MT5 disconnect: {e}")
            self._connected = False
            return {"status": "disconnected"}

    def is_connected(self) -> bool:
        """Check if connector is connected to MT5"""
        return self._connected

    async def get_account_info(self) -> AccountInfo:
        """Get current MT5 account information"""
        try:
            raw_info = self._client.get_account_info_rest()
            return AccountInfo(
                balance=float(raw_info.get('balance', 0)),
                equity=float(raw_info.get('equity', 0)),
                margin=float(raw_info.get('margin', 0)),
                free_margin=float(raw_info.get('margin_free', 0)),
                margin_level=float(raw_info.get('margin_level', 0)),
                currency=raw_info.get('currency', 'USD')
            )
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to get MT5 account info: {e}")

    async def place_trade(self, trade_request: TradeRequest) -> Dict[str, Any]:
        """Place a new trade on MT5"""
        try:
            return self._client.place_trade(
                symbol=trade_request.symbol,
                lot_size=trade_request.lot_size,
                direction=trade_request.direction,
                stop_loss=trade_request.stop_loss or 0.0,
                take_profit=trade_request.take_profit or 0.0,
                order_type=trade_request.order_type,
                limit_price=trade_request.limit_price
            )
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to place MT5 trade: {e}")

    async def close_position(self, position_id: str, volume: float, symbol: str) -> Dict[str, Any]:
        """Close an existing MT5 position"""
        try:
            return self._client.close_trade(
                ticket=int(position_id),
                volume=volume,
                symbol=symbol
            )
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to close MT5 position: {e}")

    async def modify_position_protection(
        self, 
        position_id: str, 
        symbol: str, 
        stop_loss: Optional[float] = None, 
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """Modify stop loss and/or take profit for MT5 position"""
        try:
            return self._client.modify_position_protection(
                position_id=int(position_id),
                symbol=symbol,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to modify MT5 position protection: {e}")

    async def get_position_details(self, position_id: str) -> PositionInfo:
        """Get detailed information about a specific MT5 position"""
        try:
            raw_position = self._client.get_position_by_ticket(int(position_id))
            return self._convert_mt5_position_to_standard(raw_position)
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to get MT5 position details: {e}")

    async def get_open_positions(self) -> List[PositionInfo]:
        """Get all open MT5 positions"""
        try:
            raw_positions = self._client.get_all_open_positions_rest()
            positions = raw_positions.get('open_positions', [])
            return [self._convert_mt5_position_to_standard(pos) for pos in positions]
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to get MT5 open positions: {e}")

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a pending MT5 order"""
        try:
            return self._client.cancel_order(int(order_id))
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to cancel MT5 order: {e}")

    # --- Additional helpers (not part of abstract base) ---
    async def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Fetch pending orders from MT5 REST and return raw dicts for now."""
        try:
            raw = self._client.get_all_open_positions_rest()
            all_trades = raw.get('open_positions', [])
            return [t for t in all_trades if t.get('type') == 'pending_order']
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to fetch MT5 pending orders: {e}")

    async def fetch_trade_sync_data(self, position_id: str, symbol: str) -> Dict[str, Any]:
        """Fetch standardized sync data for a position from MT5 service."""
        try:
            return self._client.fetch_trade_sync_data(position_id=int(position_id), instrument_symbol=symbol)
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to fetch MT5 trade sync data: {e}")

    async def get_live_price(self, symbol: str) -> PriceData:
        """Get current live price for a symbol from MT5"""
        try:
            raw_price = self._client.get_live_price(symbol)
            return PriceData(
                symbol=symbol,
                bid=float(raw_price.get('bid', 0)),
                ask=float(raw_price.get('ask', 0)),
                timestamp=datetime.now()
            )
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to get MT5 live price: {e}")

    async def get_historical_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        count: Optional[int] = None,
        start_time: Optional[datetime] = None, 
        end_time: Optional[datetime] = None
    ) -> List[CandleData]:
        """Get historical candle data from MT5"""
        try:
            raw_candles = self._client.get_historical_candles(
                symbol=symbol,
                timeframe=timeframe,
                count=count,
                start_time=start_time,
                end_time=end_time
            )
            
            candles = raw_candles.get('candles', [])
            out: List[CandleData] = []
            for candle in candles:
                ts_val = candle.get('time') or candle.get('timestamp')
                try:
                    if isinstance(ts_val, (int, float)):
                        ts = datetime.utcfromtimestamp(ts_val)
                    elif isinstance(ts_val, str):
                        ts = datetime.fromisoformat(ts_val.replace('Z', '+00:00'))
                    else:
                        ts = datetime.utcnow()
                except Exception:
                    ts = datetime.utcnow()
                try:
                    out.append(
                        CandleData(
                            symbol=symbol,
                            timeframe=timeframe,
                            open=float(candle.get('open', 0) or 0),
                            high=float(candle.get('high', 0) or 0),
                            low=float(candle.get('low', 0) or 0),
                            close=float(candle.get('close', 0) or 0),
                            volume=float(candle.get('tick_volume', candle.get('volume', 0)) or 0),
                            timestamp=ts,
                        )
                    )
                except Exception:
                    # Skip malformed candle
                    continue
            return out
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to get MT5 historical candles: {e}")

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get MT5 symbol information"""
        try:
            return self._client.get_symbol_info(symbol)
        except (BrokerAPIError, BrokerConnectionError) as e:
            raise ConnectionError(f"Failed to get MT5 symbol info: {e}")

    async def subscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        """Subscribe to live price updates using headless orchestrator (fanout via Channels)."""
        creds = self._creds
        await mt5_subscribe_price(
            creds['base_url'], creds['account_id'], creds['password'], creds['broker_server'], creds['internal_account_id'], symbol
        )
        logger.info(f"MT5Connector headless subscribe_price {symbol} for {creds['internal_account_id']}")
        # Callback is not used in headless path; updates are fanouted to Channels groups.

    async def unsubscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        """Unsubscribe from live price updates using headless orchestrator."""
        creds = self._creds
        await mt5_unsubscribe_price(
            creds['base_url'], creds['account_id'], creds['password'], creds['broker_server'], creds['internal_account_id'], symbol
        )
        logger.info(f"MT5Connector headless unsubscribe_price {symbol} for {creds['internal_account_id']}")

    async def subscribe_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Callable[[CandleData], None]
    ) -> None:
        """Subscribe to live candle updates using headless orchestrator (fanout via Channels)."""
        creds = self._creds
        await mt5_subscribe_candles(
            creds['base_url'], creds['account_id'], creds['password'], creds['broker_server'], creds['internal_account_id'], symbol, timeframe
        )
        logger.info(f"MT5Connector headless subscribe_candles {symbol}@{timeframe} for {creds['internal_account_id']}")
        # Callback is not used in headless path; updates are fanouted to Channels groups.

    async def unsubscribe_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Callable[[CandleData], None]
    ) -> None:
        """Unsubscribe from live candle updates using headless orchestrator."""
        creds = self._creds
        await mt5_unsubscribe_candles(
            creds['base_url'], creds['account_id'], creds['password'], creds['broker_server'], creds['internal_account_id'], symbol, timeframe
        )
        logger.info(f"MT5Connector headless unsubscribe_candles {symbol}@{timeframe} for {creds['internal_account_id']}")

    def register_account_info_listener(self, callback: Callable[[AccountInfo], None]) -> None:
        """Register listener for MT5 account info updates"""
        def mt5_account_callback(raw_data):
            account_info = AccountInfo(
                balance=float(raw_data.get('balance', 0)),
                equity=float(raw_data.get('equity', 0)),
                margin=float(raw_data.get('margin', 0)),
                free_margin=float(raw_data.get('margin_free', 0)),
                margin_level=float(raw_data.get('margin_level', 0)),
                currency=raw_data.get('currency', 'USD')
            )
            callback(account_info)
        
        self._client.register_account_info_listener(mt5_account_callback)

    def register_position_update_listener(self, callback: Callable[[List[PositionInfo]], None]) -> None:
        """Register listener for MT5 position updates"""
        def mt5_positions_callback(raw_positions):
            positions = [self._convert_mt5_position_to_standard(pos) for pos in raw_positions]
            callback(positions)
        
        self._client.register_open_positions_listener(mt5_positions_callback)

    def register_position_closed_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register listener for MT5 position closure events"""
        self._client.register_closed_position_listener(callback)

    def get_platform_name(self) -> str:
        """Return the name of the trading platform"""
        return "MT5"

    def get_supported_symbols(self) -> List[str]:
        """Get list of supported trading symbols"""
        # This would need to be implemented based on MT5 API capabilities
        # For now, return common forex pairs
        return ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"]

    def validate_symbol(self, symbol: str) -> bool:
        """Validate if a symbol is supported on MT5"""
        try:
            symbol_info = self._client.get_symbol_info(symbol)
            return symbol_info.get('select', False)
        except:
            return False

    def _convert_mt5_position_to_standard(self, mt5_position: Dict[str, Any]) -> PositionInfo:
        """Convert MT5 position format to standard PositionInfo"""
        return PositionInfo(
            position_id=str(mt5_position.get('ticket', '')),
            symbol=mt5_position.get('symbol', ''),
            direction="BUY" if mt5_position.get('type', 0) == 0 else "SELL",
            volume=float(mt5_position.get('volume', 0)),
            open_price=float(mt5_position.get('price_open', 0)),
            current_price=float(mt5_position.get('price_current', 0)),
            stop_loss=float(mt5_position.get('sl', 0)) if mt5_position.get('sl') else None,
            take_profit=float(mt5_position.get('tp', 0)) if mt5_position.get('tp') else None,
            profit=float(mt5_position.get('profit', 0)),
            swap=float(mt5_position.get('swap', 0)),
            commission=float(mt5_position.get('commission', 0))
        )
