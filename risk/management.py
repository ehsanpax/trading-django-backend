# risk/management.py
import logging
from .models import RiskManagement  # Ensure your RiskManagement model is in your accounts app
from mt5.services import MT5Connector
from trades.helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform
from trading.models import Trade
from accounts.services import get_account_details
from decimal import Decimal
from datetime import datetime, timedelta
from django.db.models import Sum, Q
from django.utils import timezone
from risk.utils import get_total_open_pnl
from risk.utils import get_account_equity

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

def calculate_position_size(account_id, symbol, account_equity, risk_percent, stop_loss_distance, take_profit_price, trade_direction, db=None, symbol_info=None, market_prices=None):
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
    print(pip_size)
    
    stop_loss_distance = float(stop_loss_distance)
    stop_loss_price = (entry_price - (stop_loss_distance * pip_size)
                       if trade_direction.upper() == "BUY"
                       else entry_price + (stop_loss_distance * pip_size))
    def get_decimals_from_pip_size(pip_size):
        d = Decimal(str(pip_size))
        return -d.as_tuple().exponent 
    # Calculate the amount at risk and pip value
    decimals = get_decimals_from_pip_size(pip_size)
    risk_amount = account_equity * (risk_percent / 100.0)
    pip_value = contract_size * pip_size
    if pip_value == 0:
        logger.error("Pip value calculation failed (division by zero)")
        return {"error": "Invalid pip value"}
    print(risk_percent)
    print(account_equity)
    print(contract_size)
    print(risk_amount, pip_value)
    lot_size = risk_amount / (stop_loss_distance * pip_value)
    lot_size = round(lot_size, 2)
    print(lot_size)
    digits = symbol_info.get("digits")
    print("digits:",  digits)
    take_profit_price=float(take_profit_price)
    stop_loss_price=float(stop_loss_price)
    tp_rounded = round(take_profit_price, decimals)
    sl_rounded = round(stop_loss_price, decimals)
    return {
        "lot_size": lot_size,
        "stop_loss_distance": stop_loss_distance,
        "stop_loss_price": sl_rounded,
        "take_profit_price": tp_rounded,
        "decimals": decimals,
    }


def validate_trade_request(account_id: str, user, symbol: str, trade_direction: str, 
                           stop_loss_distance: float, take_profit_price: float, risk_percent: float):
    """
    Validates trade parameters by calculating the appropriate lot size and stop-loss.
    In a real-world scenario, you’d retrieve symbol info and market prices from your MT5 service.
    Here, we simulate them with dummy data.
    """
    account_info = get_account_details(account_id, user)
    if "error" in account_info:
        return {"error": account_info["error"]}
    real_equity = account_info.get("equity")
    # For demonstration, using dummy symbol info and market prices:
    symbol_info = {"pip_size": 0.0001, "contract_size": 100000}
    market_prices = {"bid": 1.2050, "ask": 1.2052}
    
    try:
        calculation_result = calculate_position_size(
            account_id=account_id,
            symbol=symbol,
            account_equity=real_equity,  # Replace with the real equity retrieved from the account details
            risk_percent=risk_percent,
            stop_loss_distance=stop_loss_distance,
            trade_direction=trade_direction,
            symbol_info=symbol_info,
            take_profit_price=take_profit_price,
            market_prices=market_prices
        )
    except Exception as e:
        return {"error": str(e)}
    take_profit_price=float(take_profit_price)
    #stop_loss_price=float(stop_loss_price)
    tp_rounded = round(take_profit_price, calculation_result["decimals"])
    #sl_rounded = round(stop_loss_price, calculation_result["decimals"])
    print("DECIMLALS: ", calculation_result["decimals"])
    print("TP ROUNDED: ", tp_rounded)
    print("TAKE TP: ", take_profit_price)
    return {
        "lot_size": calculation_result["lot_size"],
        "stop_loss_price": calculation_result["stop_loss_price"],
        "take_profit_price": tp_rounded
    }



def has_exceeded_daily_loss(risk_settings) -> bool:
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    closed_trades = Trade.objects.filter(
        account=risk_settings.account,
        closed_at__gte=today_start,
        trade_status="closed"
    )
    closed_loss = closed_trades.aggregate(total_pl=Sum('actual_profit_loss'))['total_pl'] or Decimal('0.00')
    
    open_loss = get_total_open_pnl(risk_settings.account)
    total_pl = closed_loss + open_loss
    
    # Use our helper to fetch current equity.
    current_equity = get_account_equity(risk_settings.account, risk_settings.account.user)
    max_loss_threshold = current_equity * (risk_settings.max_daily_loss / Decimal('100'))
    print("CURRENT EQUITY: ",current_equity)
    print("max loss: ",max_loss_threshold)

    if total_pl < 0 and abs(total_pl) >= max_loss_threshold:
        return True
    return False

def get_consecutive_losses(risk_settings: RiskManagement) -> int:
    """
    Returns how many trades have been lost in a row.
    We look for the most recent trades and count consecutive losers.
    """
    # Sort trades by closed_at descending
    recent_closed_trades = Trade.objects.filter(
        account=risk_settings.account,
        trade_status="closed"
    ).order_by('-closed_at')

    consecutive_loses = 0
    for t in recent_closed_trades:
        if t.actual_profit_loss is not None and t.actual_profit_loss < 0:
            consecutive_loses += 1
        else:
            # If we hit a winning trade, break out of the loop
            break

    return consecutive_loses

def is_cooldown_active(risk_settings: RiskManagement) -> bool:
    """
    Checks if the account is currently in a cooldown period due to exceeding
    consecutive_loss_limit.
    """
    if not risk_settings.enforce_cooldowns:
        return False  # If cooldowns not enforced, skip

    # 1️⃣ If consecutive losses < limit, no cooldown
    consecutive_losses = get_consecutive_losses(risk_settings)
    if consecutive_losses < risk_settings.consecutive_loss_limit:
        return False

    # 2️⃣ If we exceeded consecutive_loss_limit, figure out when the last trade closed
    # and see if the cooldown period has elapsed.
    last_trade = Trade.objects.filter(
        account=risk_settings.account,
        trade_status="closed"
    ).order_by('-closed_at').first()

    if not last_trade or not last_trade.closed_at:
        return False

    # 3️⃣ Compare last_trade.closed_at to now - if we’re still within cooldown, return True
    cooldown_expiry = last_trade.closed_at + risk_settings.cooldown_period
    if timezone.now() < cooldown_expiry:
        logger.warning(f"Cooldown still active until {cooldown_expiry}")
        return True
    return False

def exceeds_max_lot_size(risk_settings: RiskManagement, proposed_lot: Decimal) -> bool:
    """
    Checks if the proposed lot size is larger than the max_lot_size.
    """
    if proposed_lot > risk_settings.max_lot_size:
        logger.warning(f"Proposed lot size {proposed_lot} exceeds max {risk_settings.max_lot_size}")
        return True
    return False

def exceeds_max_trades_same_symbol(risk_settings: RiskManagement, symbol: str) -> bool:
    """
    Checks if the user already has open trades on the same symbol beyond the allowed max.
    """
    open_trades_same_symbol = Trade.objects.filter(
        account=risk_settings.account,
        instrument=symbol,
        trade_status="open"
    ).count()

    if open_trades_same_symbol >= risk_settings.max_open_trades_same_symbol:
        logger.warning(f"Open trades on {symbol} = {open_trades_same_symbol}, exceeds max allowed.")
        return True
    return False

def perform_risk_checks(risk_settings: RiskManagement, proposed_lot: Decimal, symbol: str) -> dict:
    """
    Calls the guard-rail checks in sequence. If any fail, returns an error dict.
    Otherwise returns an empty dict indicating all checks passed.
    """
    # 1️⃣ Check daily loss
    if has_exceeded_daily_loss(risk_settings):
        return {"error": "Max daily loss limit reached. No further trades allowed today."}

    # 2️⃣ Check consecutive losses & cooldown
    if is_cooldown_active(risk_settings):
        return {"error": "Cooldown period is active due to consecutive losing trades."}

    # 3️⃣ Check max lot size
    if exceeds_max_lot_size(risk_settings, proposed_lot):
        return {"error": f"Proposed lot size {proposed_lot} exceeds the allowed maximum."}

    # 4️⃣ Check open trades for the same symbol
    if exceeds_max_trades_same_symbol(risk_settings, symbol):
        return {"error": "Too many open trades on the same symbol."}

    # If all checks pass, return an empty dict
    return {}
