# Platform-Agnostic Trading Architecture Implementation Guide

## Overview

This document provides a comprehensive guide for implementing new trading platform integrations using our platform-agnostic architecture. This design allows external developers to integrate new platforms without touching core business logic.

## Architecture Benefits

### For Platform Integrators
- **Isolated Development**: Work only on connector implementation without seeing core business logic
- **Standardized Interface**: Clear contract to implement via `TradingPlatformConnector`
- **Template-Based**: Follow existing patterns (MT5Connector example)
- **Comprehensive Documentation**: All requirements clearly specified

### For Core Platform
- **No Business Logic Changes**: New platforms require zero changes to services
- **Consistent Behavior**: All platforms behave identically from service perspective
- **Easy Maintenance**: Platform-specific logic isolated in connectors
- **Future-Proof**: Easy to add new platforms or modify existing ones

## Integration Process

### Step 1: Understand the Interface

All platform connectors must implement `TradingPlatformConnector` from `connectors/base.py`:

```python
class TradingPlatformConnector(ABC):
    # Connection Management
    async def connect(self) -> Dict[str, Any]
    async def disconnect(self) -> Dict[str, Any]
    def is_connected(self) -> bool
    
    # Account Operations
    async def get_account_info(self) -> AccountInfo
    
    # Position Management
    async def place_trade(self, trade_request: TradeRequest) -> Dict[str, Any]
    async def close_position(self, position_id: str, volume: float, symbol: str) -> Dict[str, Any]
    async def modify_position_protection(self, position_id: str, symbol: str, stop_loss: Optional[float], take_profit: Optional[float]) -> Dict[str, Any]
    async def get_position_details(self, position_id: str) -> PositionInfo
    async def get_open_positions(self) -> List[PositionInfo]
    
    # Order Management
    async def cancel_order(self, order_id: str) -> Dict[str, Any]
    
    # Market Data
    async def get_live_price(self, symbol: str) -> PriceData
    async def get_historical_candles(self, symbol: str, timeframe: str, count: Optional[int], start_time: Optional[datetime], end_time: Optional[datetime]) -> List[CandleData]
    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]
    
    # Live Data Subscriptions
    async def subscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None
    async def unsubscribe_price(self, symbol: str, callback: Callable[[PriceData], None]) -> None
    async def subscribe_candles(self, symbol: str, timeframe: str, callback: Callable[[CandleData], None]) -> None
    async def unsubscribe_candles(self, symbol: str, timeframe: str, callback: Callable[[CandleData], None]) -> None
    
    # Event Listeners
    def register_account_info_listener(self, callback: Callable[[AccountInfo], None]) -> None
    def register_position_update_listener(self, callback: Callable[[List[PositionInfo]], None]) -> None
    def register_position_closed_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None
    
    # Utility Methods
    def get_platform_name(self) -> str
    def get_supported_symbols(self) -> List[str]
    def validate_symbol(self, symbol: str) -> bool
```

### Step 2: Create Connector Implementation

#### File Structure
```
connectors/
├── base.py                 # Interface definition (READ ONLY)
├── factory.py             # Registration system (MODIFY ONLY for registration)
├── mt5_connector.py       # MT5 example implementation (REFERENCE ONLY)
├── your_platform_connector.py  # YOUR IMPLEMENTATION
└── trading_service.py     # Service layer (READ ONLY)
```

#### Implementation Template
```python
# connectors/your_platform_connector.py

from .base import TradingPlatformConnector, TradeRequest, PositionInfo, AccountInfo, PriceData, CandleData

class YourPlatformConnector(TradingPlatformConnector):
    def __init__(self, account_credentials: Dict[str, Any]):
        # Initialize with platform-specific credentials
        # Validate required fields
        # Set up platform client
        pass
    
    async def connect(self) -> Dict[str, Any]:
        # Establish connection to platform
        # Handle authentication
        # Return connection status
        pass
    
    # Implement all other methods...
```

### Step 3: Data Format Standardization

#### Standard Data Types

All connectors must return data in these standardized formats:

**TradeRequest** (Input)
```python
@dataclass
class TradeRequest:
    symbol: str
    lot_size: float
    direction: str  # "BUY" or "SELL"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    order_type: str = "MARKET"  # "MARKET" or "LIMIT"
    limit_price: Optional[float] = None
```

**PositionInfo** (Output)
```python
@dataclass
class PositionInfo:
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
```

**AccountInfo** (Output)
```python
@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    currency: str
```

### Step 4: Error Handling

Use standardized exceptions from `connectors/base.py`:

```python
from .base import ConnectionError, AuthenticationError, UnsupportedOperationError

# In your connector methods:
try:
    # Platform-specific operation
    result = your_platform_api.some_operation()
    return standardize_result(result)
except YourPlatformException as e:
    raise ConnectionError(f"Platform operation failed: {e}")
```

### Step 5: Registration

After implementing your connector, register it in `connectors/factory.py`:

```python
# Add your credential mapper
def map_your_platform_credentials(account: Account) -> Dict[str, Any]:
    """Map Account to YourPlatform connector credentials"""
    your_acc = get_object_or_404(YourPlatformAccount, account=account)
    return {
        'api_key': your_acc.api_key,
        'api_secret': your_acc.api_secret,
        'sandbox': your_acc.is_sandbox,
        'internal_account_id': str(account.id),
    }

# Register your connector
register_connector("YourPlatform", YourPlatformConnector, map_your_platform_credentials)
```

## Implementation Examples

### Connection Management
```python
async def connect(self) -> Dict[str, Any]:
    try:
        # Initialize platform client
        self._client = YourPlatformClient(
            api_key=self.api_key,
            api_secret=self.api_secret,
            sandbox=self.sandbox
        )
        
        # Authenticate
        auth_result = await self._client.authenticate()
        if not auth_result.success:
            raise AuthenticationError("Failed to authenticate")
        
        self._connected = True
        return {"status": "connected", "session_id": auth_result.session_id}
        
    except Exception as e:
        raise ConnectionError(f"Failed to connect: {e}")
```

### Trade Placement
```python
async def place_trade(self, trade_request: TradeRequest) -> Dict[str, Any]:
    try:
        # Convert to platform format
        platform_request = {
            'instrument': trade_request.symbol,
            'units': int(trade_request.lot_size * 100000),  # Convert to units
            'side': 'long' if trade_request.direction == 'BUY' else 'short',
            'type': trade_request.order_type.lower(),
        }
        
        if trade_request.stop_loss:
            platform_request['stopLoss'] = trade_request.stop_loss
        if trade_request.take_profit:
            platform_request['takeProfit'] = trade_request.take_profit
            
        # Execute on platform
        result = await self._client.create_order(platform_request)
        
        # Return standardized response
        return {
            "status": "success",
            "order_id": result.order_id,
            "position_id": result.position_id,
            "fill_price": result.fill_price,
            "message": "Trade executed successfully"
        }
        
    except YourPlatformError as e:
        raise ConnectionError(f"Failed to place trade: {e}")
```

### Position Information Conversion
```python
def _convert_to_standard_position(self, platform_position) -> PositionInfo:
    return PositionInfo(
        position_id=str(platform_position.id),
        symbol=platform_position.instrument,
        direction="BUY" if platform_position.side == "long" else "SELL",
        volume=abs(platform_position.units) / 100000,  # Convert to lots
        open_price=platform_position.avg_price,
        current_price=platform_position.mark_price,
        stop_loss=platform_position.stop_loss_price,
        take_profit=platform_position.take_profit_price,
        profit=platform_position.unrealized_pnl,
        swap=platform_position.financing,
        commission=platform_position.commission
    )
```

## Testing Guidelines

### Unit Tests
Create comprehensive unit tests for your connector:

```python
# tests/test_your_platform_connector.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from connectors.your_platform_connector import YourPlatformConnector

class TestYourPlatformConnector:
    def setup_method(self):
        self.credentials = {
            'api_key': 'test_key',
            'api_secret': 'test_secret',
            'sandbox': True,
            'internal_account_id': 'test_account'
        }
        self.connector = YourPlatformConnector(self.credentials)
    
    @pytest.mark.asyncio
    async def test_connect_success(self):
        # Mock platform client
        self.connector._client = AsyncMock()
        self.connector._client.authenticate.return_value = MagicMock(success=True, session_id="123")
        
        result = await self.connector.connect()
        
        assert result["status"] == "connected"
        assert self.connector.is_connected()
    
    @pytest.mark.asyncio
    async def test_place_trade(self):
        # Test trade placement
        trade_request = TradeRequest(
            symbol="EURUSD",
            lot_size=0.1,
            direction="BUY",
            stop_loss=1.1000,
            take_profit=1.1100
        )
        
        # Mock platform response
        self.connector._client = AsyncMock()
        self.connector._client.create_order.return_value = MagicMock(
            order_id="order123",
            position_id="pos456",
            fill_price=1.1050
        )
        
        result = await self.connector.place_trade(trade_request)
        
        assert result["status"] == "success"
        assert result["position_id"] == "pos456"
```

### Integration Tests
Test with platform sandbox/demo environment:

```python
@pytest.mark.integration
class TestYourPlatformIntegration:
    def setup_method(self):
        self.connector = YourPlatformConnector({
            'api_key': os.getenv('YOUR_PLATFORM_DEMO_KEY'),
            'api_secret': os.getenv('YOUR_PLATFORM_DEMO_SECRET'),
            'sandbox': True,
            'internal_account_id': 'integration_test'
        })
    
    @pytest.mark.asyncio
    async def test_full_trade_lifecycle(self):
        # Connect
        await self.connector.connect()
        
        # Place trade
        trade_request = TradeRequest(symbol="EURUSD", lot_size=0.01, direction="BUY")
        trade_result = await self.connector.place_trade(trade_request)
        position_id = trade_result["position_id"]
        
        # Get position details
        position = await self.connector.get_position_details(position_id)
        assert position.symbol == "EURUSD"
        
        # Close position
        close_result = await self.connector.close_position(position_id, 0.01, "EURUSD")
        assert close_result["status"] == "success"
        
        # Disconnect
        await self.connector.disconnect()
```

## Deployment Checklist

### Before Production
- [ ] All abstract methods implemented
- [ ] Unit tests pass (>95% coverage)
- [ ] Integration tests pass with sandbox
- [ ] Error handling comprehensive
- [ ] Data conversion verified
- [ ] Performance acceptable
- [ ] Security review completed
- [ ] Documentation updated

### Production Setup
- [ ] Platform credentials configured
- [ ] Connector registered in factory
- [ ] Monitoring/logging configured
- [ ] Error alerting setup
- [ ] Rollback plan prepared

## Support and Troubleshooting

### Common Issues

**Authentication Failures**
- Verify credentials in account model
- Check credential mapping function
- Ensure platform API keys are valid

**Data Format Errors**
- Validate all returned data matches standard types
- Check for required fields
- Ensure proper type conversions

**Connection Issues**
- Implement proper retry logic
- Handle network timeouts
- Validate platform endpoint URLs

### Getting Help

1. Review existing MT5Connector implementation
2. Check interface documentation in base.py
3. Run provided unit test templates
4. Contact platform team for integration support

## Platform-Specific Notes

### cTrader Integration
- Use Protocol Buffers for communication
- Handle OAuth2 token refresh
- Implement proper WebSocket management
- Map cTrader position/order IDs correctly

### Future Platforms
- Follow this same pattern
- Extend base interface if needed (with approval)
- Document platform-specific considerations
- Update this guide with lessons learned

## Conclusion

This architecture ensures that:
1. **External developers** can integrate new platforms without core access
2. **Core services** remain platform-agnostic and maintainable  
3. **Business logic** stays isolated from platform specifics
4. **New platforms** integrate seamlessly with existing functionality

The key is strict adherence to the interface contract and proper data format standardization.
