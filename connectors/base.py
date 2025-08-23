# connectors/base.py
"""
Base connector interface that all trading platform connectors must implement.
This ensures consistent API across all platforms and allows for easy integration
of new platforms without modifying core business logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Callable
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass


@dataclass
class TradeRequest:
    """Standardized trade request structure"""
    symbol: str
    lot_size: float
    direction: str  # "BUY" or "SELL"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    order_type: str = "MARKET"  # "MARKET" or "LIMIT"
    limit_price: Optional[float] = None
    # Optional: distances (in pips/points, platform-specific) for MARKET orders
    sl_distance: Optional[float] = None
    tp_distance: Optional[float] = None


@dataclass
class PositionInfo:
    """Standardized position information structure"""
    position_id: str
    symbol: str
    direction: str
    volume: float
    open_price: float
    current_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    profit: float
    swap: float
    commission: float


@dataclass
class AccountInfo:
    """Standardized account information structure"""
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str


@dataclass
class PriceData:
    """Standardized price data structure"""
    symbol: str
    bid: float
    ask: float
    timestamp: datetime


@dataclass
class CandleData:
    """Standardized candle data structure"""
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime


class TradingPlatformConnector(ABC):
    """
    Abstract base class for all trading platform connectors.
    New platform integrations must implement this interface.
    """

    @abstractmethod
    def __init__(self, account_credentials: Dict[str, Any]):
        """Initialize connector with platform-specific credentials"""
        pass

    # Connection Management
    @abstractmethod
    async def connect(self) -> Dict[str, Any]:
        """Establish connection to the trading platform"""
        pass

    @abstractmethod
    async def disconnect(self) -> Dict[str, Any]:
        """Disconnect from the trading platform"""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connector is connected to platform"""
        pass

    # Account Operations
    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Get current account information"""
        pass

    # Position Management
    @abstractmethod
    async def place_trade(self, trade_request: TradeRequest) -> Dict[str, Any]:
        """Place a new trade"""
        pass

    @abstractmethod
    async def close_position(self, position_id: str, volume: float, symbol: str) -> Dict[str, Any]:
        """Close an existing position"""
        pass

    @abstractmethod
    async def modify_position_protection(
        self, 
        position_id: str, 
        symbol: str, 
        stop_loss: Optional[float] = None, 
        take_profit: Optional[float] = None
    ) -> Dict[str, Any]:
        """Modify stop loss and/or take profit for a position"""
        pass

    @abstractmethod
    async def get_position_details(self, position_id: str) -> PositionInfo:
        """Get detailed information about a specific position"""
        pass

    @abstractmethod
    async def get_open_positions(self) -> List[PositionInfo]:
        """Get all open positions"""
        pass

    # Order Management
    @abstractmethod
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel a pending order"""
        pass

    # Market Data
    @abstractmethod
    async def get_live_price(self, symbol: str) -> PriceData:
        """Get current live price for a symbol"""
        pass

    @abstractmethod
    async def get_historical_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        count: Optional[int] = None,
        start_time: Optional[datetime] = None, 
        end_time: Optional[datetime] = None
    ) -> List[CandleData]:
        """Get historical candle data"""
        pass

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get symbol information (pip size, lot size, etc.)"""
        pass

    # Live Data Subscriptions
    @abstractmethod
    async def subscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        """Subscribe to live price updates"""
        pass

    @abstractmethod
    async def unsubscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None:
        """Unsubscribe from live price updates"""
        pass

    @abstractmethod
    async def subscribe_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Callable[[CandleData], None]
    ) -> None:
        """Subscribe to live candle updates"""
        pass

    @abstractmethod
    async def unsubscribe_candles(
        self, 
        symbol: str, 
        timeframe: str, 
        callback: Callable[[CandleData], None]
    ) -> None:
        """Unsubscribe from live candle updates"""
        pass

    # Event Listeners
    @abstractmethod
    def register_account_info_listener(self, callback: Callable[[AccountInfo], None]) -> None:
        """Register listener for account info updates"""
        pass

    @abstractmethod
    def register_position_update_listener(self, callback: Callable[[List[PositionInfo]], None]) -> None:
        """Register listener for position updates"""
        pass

    @abstractmethod
    def register_position_closed_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register listener for position closure events"""
        pass

    # Utility Methods
    @abstractmethod
    def get_platform_name(self) -> str:
        """Return the name of the trading platform"""
        pass

    @abstractmethod
    def get_supported_symbols(self) -> List[str]:
        """Get list of supported trading symbols"""
        pass

    @abstractmethod
    def validate_symbol(self, symbol: str) -> bool:
        """Validate if a symbol is supported on this platform"""
        pass


class ConnectorError(Exception):
    """Base exception for connector-related errors"""
    pass


class ConnectionError(ConnectorError):
    """Raised when connection to platform fails"""
    pass


class AuthenticationError(ConnectorError):
    """Raised when authentication with platform fails"""
    pass


class UnsupportedOperationError(ConnectorError):
    """Raised when an operation is not supported by the platform"""
    pass
