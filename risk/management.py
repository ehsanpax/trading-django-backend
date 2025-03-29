# risk/management.py
import logging
from trading.models import RiskManagement  # Ensure your RiskManagement model is in your accounts app
from mt5.services import MT5Connector
from trades.helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform

logger = logging.getLogger(__name__)

def fetch_risk_settings(account_id: str):
    """
    Retrieve risk settings for a given account. If not found, return default settings.
    """
    try:
        risk_settings = RiskManagement.objects.get(account_id=account_id)
        return risk_settings
    except RiskManagement.DoesNotExist:
        # Return default risk settings
        return {
            "max_trade_risk": 3.0,         # Maximum allowed trade risk (or lot size)
            "max_open_positions": 3,       # Maximum open trades allowed
            "max_daily_loss": 1,           # Maximum daily loss (as a percentage)
            "enforce_cooldowns": True,
            "consecutive_loss_limit": 3
        }

# risk/management.py
import logging

logger = logging.getLogger(__name__)

def calculate_position_size(account_id, symbol, account_equity, risk_percent, stop_loss_distance, trade_direction, db=None, symbol_info=None, market_prices=None):
    """
    Calculates position size based on risk parameters.
    
    For this endpoint, we assume symbol information and market prices are available.
    In a real-world setup you’d fetch these details (e.g. via your MT5Connector service).
    Here we use dummy values:
      - pip_size: 0.0001
      - contract_size: 100000
      - market_prices: bid and ask values for the symbol.
    """
    # Dummy symbol info – in a real app, fetch from your connector or cache
    symbol_info = fetch_symbol_info_for_platform(account_id, symbol)
    if "error" in symbol_info:
            return {"error": f"Failed to fetch symbol info: {symbol_info['error']}"}

    pip_size = symbol_info.get("pip_size")
    contract_size = symbol_info.get("contract_size")
    
    # Dummy market prices – in a real app, use live data from your MT5 service
    market_prices = fetch_live_price_for_platform(account_id, symbol)
    if "error" in market_prices:
        return {"error": f"Failed to fetch market price: {market_prices['error']}"}

    entry_price = market_prices["ask"] if trade_direction.upper() == "SELL" else market_prices["bid"]
    if entry_price is None:
        raise ValueError("Market price fetch failed – entry price is None")
    
    logger.info(f"Fetched entry_price: {entry_price}")
    
    # Calculate the stop-loss price based on direction
    print(f"pip size is: {pip_size}")
    stop_loss_distance = float(stop_loss_distance)
    stop_loss_price = (entry_price - (stop_loss_distance * pip_size)
                       if trade_direction.upper() == "BUY"
                       else entry_price + (stop_loss_distance * pip_size))
    
    # Calculate the amount at risk and pip value
    risk_amount = account_equity * (risk_percent / 100.0)
    pip_value = contract_size * pip_size
    if pip_value == 0:
        logger.error("Pip value calculation failed (division by zero)")
        return {"error": "Invalid pip value"}
    
    lot_size = risk_amount / (stop_loss_distance * pip_value)
    lot_size = round(lot_size, 2)
    
    return {
        "lot_size": lot_size,
        "stop_loss_distance": round(stop_loss_distance, 1),
        "stop_loss_price": round(stop_loss_price, 5)
    }


def validate_trade_request(account_id: str, symbol: str, trade_direction: str, 
                           stop_loss_distance: float, take_profit_price: float, risk_percent: float):
    """
    Validates trade parameters by calculating the appropriate lot size and stop-loss.
    In a real-world scenario, you’d retrieve symbol info and market prices from your MT5 service.
    Here, we simulate them with dummy data.
    """
    # For demonstration, using dummy symbol info and market prices:
    symbol_info = {"pip_size": 0.0001, "contract_size": 100000}
    market_prices = {"bid": 1.2050, "ask": 1.2052}
    
    try:
        calculation_result = calculate_position_size(
            account_id=account_id,
            symbol=symbol,
            account_equity=10000,  # Replace with the real equity retrieved from the account details
            risk_percent=risk_percent,
            stop_loss_distance=stop_loss_distance,
            trade_direction=trade_direction,
            symbol_info=symbol_info,
            market_prices=market_prices
        )
    except Exception as e:
        return {"error": str(e)}
    
    return {
        "lot_size": calculation_result["lot_size"],
        "stop_loss_price": calculation_result["stop_loss_price"],
        "take_profit_price": take_profit_price
    }
