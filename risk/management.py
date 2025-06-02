# risk/management.py
import logging
from .models import RiskManagement  # Ensure your RiskManagement model is in your accounts app
from mt5.services import MT5Connector
from trades.helpers import fetch_symbol_info_for_platform, fetch_live_price_for_platform
from trading.models import Trade
from accounts.services import get_account_details
from accounts.models import Account # Added import for Account model
from decimal import Decimal
from datetime import datetime, timedelta
from django.db.models import Sum, Q
from django.utils import timezone
from risk.utils import get_total_open_pnl
from risk.utils import get_account_equity
import string


logger = logging.getLogger(__name__)

def is_forex_pair(sym):
    return (
        len(sym) == 6
        and sym[:3].isalpha()
        and sym[3:].isalpha()
    )

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

    pip_value_raw = contract_size * pip_size

    if is_forex_pair(symbol):
        # it's something like EURUSD or USDJPY
        quote = symbol[-3:].upper()
        if quote == "USD":
            pip_value = pip_value_raw
        else:
            pip_value = pip_value_raw / entry_price
    else:
        # non-FX instrument (e.g. U500, BTCUSD, GOLD)
        pip_value = pip_value_raw

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
        print("CALCULATION RESULT: ", calculation_result)
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



def has_exceeded_daily_loss(account: Account, max_daily_loss_percent_setting: Decimal) -> bool:
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    closed_trades = Trade.objects.filter(
        account=account, # Use passed account
        closed_at__gte=today_start,
        trade_status="closed"
    )
    closed_loss = closed_trades.aggregate(total_pl=Sum('actual_profit_loss'))['total_pl'] or Decimal('0.00')
    
    open_loss = get_total_open_pnl(account) # Use passed account
    total_pl = closed_loss + open_loss
    
    # Use our helper to fetch current equity.
    # Ensure account.user is accessible; if Account model doesn't directly link user like that, adjust as needed.
    # Assuming get_account_equity can derive user or doesn't strictly need it if account object is rich enough.
    current_equity = get_account_equity(account, getattr(account, 'user', None)) 
    max_loss_threshold = current_equity * (max_daily_loss_percent_setting / Decimal('100'))
    
    logger.debug(f"Account {account.id}: Current Equity: {current_equity}, Max Daily Loss Threshold: {max_loss_threshold}, Total P/L Today: {total_pl}")

    if total_pl < 0 and abs(total_pl) >= max_loss_threshold:
        logger.warning(f"Account {account.id} exceeded daily loss limit. Loss: {total_pl}, Threshold: {max_loss_threshold}")
        return True
    return False

def get_consecutive_losses(account: Account) -> int:
    """
    Returns how many trades have been lost in a row *today*.
    We look for the most recent trades closed today and count consecutive losers.
    """
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Filter for trades closed today and sort by closed_at descending
    recent_closed_trades_today = Trade.objects.filter(
        account=account, # Use passed account
        trade_status="closed",
        closed_at__gte=today_start  # Filter for today
    ).order_by('-closed_at')

    consecutive_loses = 0
    for t in recent_closed_trades_today:
        if t.actual_profit_loss is not None and t.actual_profit_loss < 0:
            consecutive_loses += 1
        else:
            # If we hit a winning trade (or a trade not yet assessed for P/L), break
            break

    return consecutive_loses

def is_cooldown_active(account: Account, consecutive_loss_limit_setting: int, cooldown_period_setting: timedelta, enforce_cooldowns_setting: bool) -> bool:
    """
    Checks if the account is currently in a cooldown period due to exceeding
    consecutive_loss_limit *for today's trades*.
    """
    if not enforce_cooldowns_setting: # Use passed setting
        return False

    consecutive_losses_today = get_consecutive_losses(account) # Pass account
    if consecutive_losses_today < consecutive_loss_limit_setting: # Use passed setting
        return False

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    last_losing_trade_today = Trade.objects.filter(
        account=account, # Use passed account
        trade_status="closed",
        actual_profit_loss__lt=0,
        closed_at__gte=today_start
    ).order_by('-closed_at').first()

    if not last_losing_trade_today or not last_losing_trade_today.closed_at:
        return False

    cooldown_expiry = last_losing_trade_today.closed_at + cooldown_period_setting # Use passed setting
    if timezone.now() < cooldown_expiry:
        logger.warning(f"Account {account.id} cooldown (from today's losses) still active until {cooldown_expiry}")
        return True
        
    return False

def exceeds_max_lot_size(max_lot_size_setting: Decimal, proposed_lot: Decimal) -> bool:
    """
    Checks if the proposed lot size is larger than the max_lot_size.
    """
    if proposed_lot > max_lot_size_setting: # Use passed setting
        logger.warning(f"Proposed lot size {proposed_lot} exceeds max {max_lot_size_setting}")
        return True
    return False

def exceeds_max_trades_same_symbol(account: Account, max_open_trades_same_symbol_setting: int, symbol: str) -> bool:
    """
    Checks if the user already has open trades on the same symbol beyond the allowed max.
    """
    open_trades_same_symbol = Trade.objects.filter(
        account=account, # Use passed account
        instrument=symbol,
        trade_status="open"
    ).count()

    if open_trades_same_symbol >= max_open_trades_same_symbol_setting: # Use passed setting
        logger.warning(f"Account {account.id} open trades on {symbol} = {open_trades_same_symbol}, exceeds max allowed {max_open_trades_same_symbol_setting}.")
        return True
    return False

def exceeds_max_open_positions(account: Account, max_open_positions_setting: int) -> bool:
    """
    Checks if the total number of open positions for the account exceeds the allowed maximum.
    """
    current_open_positions = Trade.objects.filter(
        account=account,
        trade_status="open"
    ).count()
    if current_open_positions >= max_open_positions_setting:
        logger.warning(f"Account {account.id} has {current_open_positions} open positions, exceeds max {max_open_positions_setting}.")
        return True
    return False

def validate_trade_risk(trade_risk_percent, risk_settings):
    """
    Validates that the trade's risk percentage does not exceed the maximum allowed risk percent.
    trade_risk_percent: Decimal representing risk percent for the trade (e.g., 1.5 for 1.5%)
    risk_settings: instance of RiskManagement with a max_trade_risk field.
    Returns: None if valid, or an error dict if invalid.
    """
    # Convert both values to Decimal to ensure precision.
    # This function might also need adjustment if risk_settings can be a dict.
    # For now, assuming it's called with a model instance or the value is extracted before calling.
    # If risk_settings can be a dict here, it should be:
    # max_allowed_risk = Decimal(risk_settings.get('max_trade_risk')) if isinstance(risk_settings, dict) else Decimal(risk_settings.max_trade_risk)

    trade_risk = Decimal(str(trade_risk_percent)) # Ensure conversion from float/str
    
    # Determine max_allowed_risk based on type of risk_settings
    if isinstance(risk_settings, dict):
        max_allowed_risk_val = risk_settings.get('max_trade_risk')
    elif hasattr(risk_settings, 'max_trade_risk'):
        max_allowed_risk_val = risk_settings.max_trade_risk
    else: # Should not happen if called correctly
        return {"error": "Max trade risk setting not found."}

    if max_allowed_risk_val is None:
         return {"error": "Max trade risk setting is not configured."}

    max_allowed_risk = Decimal(str(max_allowed_risk_val)) # Ensure conversion

    if trade_risk > max_allowed_risk:
        return {"error": f"Trade risk {trade_risk}% exceeds the allowed maximum of {max_allowed_risk}%."}
    return {}

def perform_risk_checks(account: Account,
                        risk_settings_obj_or_dict, 
                        proposed_lot: Decimal, 
                        symbol: str, 
                        trade_risk_percent: Decimal) -> dict:
    """
    Calls the guard-rail checks in sequence. If any fail, returns an error dict.
    Otherwise returns an empty dict indicating all checks passed.
    'account' is the Account model instance.
    'risk_settings_obj_or_dict' can be a RiskManagement model instance or a dict of defaults.
    """

    is_model_instance = not isinstance(risk_settings_obj_or_dict, dict)

    # 1️⃣ Check daily loss
    if is_model_instance:
        max_daily_loss_val = getattr(risk_settings_obj_or_dict, 'max_daily_loss', None)
    else: # it's a dict
        max_daily_loss_val = risk_settings_obj_or_dict.get('max_daily_loss')
    
    if max_daily_loss_val is not None:
        if has_exceeded_daily_loss(account, Decimal(str(max_daily_loss_val))):
            return {"error": "Max daily loss limit reached. No further trades allowed today."}

    # 2️⃣ Check consecutive losses & cooldown
    if is_model_instance:
        enforce_cooldowns_val = getattr(risk_settings_obj_or_dict, 'enforce_cooldowns', False)
        consecutive_loss_limit_val = getattr(risk_settings_obj_or_dict, 'consecutive_loss_limit', None)
        # Assuming RiskManagement model has 'cooldown_period' (DurationField)
        cooldown_period_val = getattr(risk_settings_obj_or_dict, 'cooldown_period', timedelta(hours=24)) 
    else: # it's a dict
        enforce_cooldowns_val = risk_settings_obj_or_dict.get('enforce_cooldowns', False)
        consecutive_loss_limit_val = risk_settings_obj_or_dict.get('consecutive_loss_limit')
        # Default dict might not have 'cooldown_period', so provide a default.
        cooldown_period_val = risk_settings_obj_or_dict.get('cooldown_period', timedelta(hours=24))

    if enforce_cooldowns_val and consecutive_loss_limit_val is not None:
        if is_cooldown_active(account, consecutive_loss_limit_val, cooldown_period_val, enforce_cooldowns_val):
            return {"error": "Cooldown period is active due to consecutive losing trades."}

    # 3️⃣ Check max lot size
    max_lot_size_val = None
    if is_model_instance and hasattr(risk_settings_obj_or_dict, 'max_lot_size'):
        max_lot_size_val = risk_settings_obj_or_dict.max_lot_size
    elif not is_model_instance: # it's a dict
        max_lot_size_val = risk_settings_obj_or_dict.get('max_lot_size') # Default dict might not have this

    if max_lot_size_val is not None:
        if exceeds_max_lot_size(Decimal(str(max_lot_size_val)), proposed_lot):
            return {"error": f"Proposed lot size {proposed_lot} exceeds the allowed maximum {max_lot_size_val}."}

    # 4️⃣ Check open trades for the same symbol
    max_open_trades_same_symbol_val = None
    if is_model_instance and hasattr(risk_settings_obj_or_dict, 'max_open_trades_same_symbol'):
        max_open_trades_same_symbol_val = risk_settings_obj_or_dict.max_open_trades_same_symbol
    elif not is_model_instance: # it's a dict
        max_open_trades_same_symbol_val = risk_settings_obj_or_dict.get('max_open_trades_same_symbol') # Default dict might not have this
        
    if max_open_trades_same_symbol_val is not None:
        if exceeds_max_trades_same_symbol(account, max_open_trades_same_symbol_val, symbol):
            return {"error": "Too many open trades on the same symbol."}
    
    # 5️⃣ Check trade risk percentage against max_trade_risk.
    if is_model_instance:
        max_trade_risk_val = getattr(risk_settings_obj_or_dict, 'max_trade_risk', None)
    else: # it's a dict
        max_trade_risk_val = risk_settings_obj_or_dict.get('max_trade_risk')

    if max_trade_risk_val is not None:
        trade_risk_percent_decimal = Decimal(str(trade_risk_percent)).quantize(Decimal("0.01"))
        if trade_risk_percent_decimal > Decimal(str(max_trade_risk_val)):
            return {"error": f"Trade risk {trade_risk_percent_decimal}% exceeds the allowed maximum of {Decimal(str(max_trade_risk_val))}%."}

    # 6️⃣ Check max total open positions
    max_open_positions_val = None
    if is_model_instance and hasattr(risk_settings_obj_or_dict, 'max_open_positions'):
        max_open_positions_val = risk_settings_obj_or_dict.max_open_positions
    elif not is_model_instance: # it's a dict
        max_open_positions_val = risk_settings_obj_or_dict.get('max_open_positions') # Default dict has this

    if max_open_positions_val is not None:
        if exceeds_max_open_positions(account, max_open_positions_val):
            return {"error": "Maximum number of total open positions reached."}
            
    # If all checks pass, return an empty dict
    return {}
