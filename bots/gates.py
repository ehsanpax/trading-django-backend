import pandas as pd
from decimal import Decimal
from bots.models import ExecutionConfig

def evaluate_filters(ts: pd.Timestamp, row: pd.Series, filters_cfg: dict) -> tuple[bool, str|None]:
    """
    Evaluates if the current bar is eligible for trading based on filter configurations.
    (e.g., session times, day of week, news events).
    
    Returns:
        A tuple of (is_eligible, reason_if_not).
    """
    # Day of week filter
    allowed_days = filters_cfg.get("allowed_days_of_week") # e.g., [0, 1, 2, 3, 4] for Mon-Fri
    if allowed_days and ts.dayofweek not in allowed_days:
        return False, f"day_of_week_disallowed_{ts.day_name()}"

    # Session time filter
    allowed_sessions = filters_cfg.get("allowed_sessions") # e.g., [{"start": "09:00", "end": "17:00"}]
    if allowed_sessions:
        time_in_session = False
        current_time = ts.time()
        for session in allowed_sessions:
            start_time = pd.to_datetime(session['start']).time()
            end_time = pd.to_datetime(session['end']).time()
            if start_time <= current_time < end_time:
                time_in_session = True
                break
        if not time_in_session:
            return False, "outside_trading_session"
            
    return True, None

def risk_allows_entry(open_positions, equity_series, ts, risk: dict, initial_equity: float) -> tuple[bool, str|None]:
    """
    Checks if a new entry is allowed based on risk management rules.
    """
    # Check max open positions
    max_open = risk.get("max_open_positions")
    if max_open is not None and len(open_positions) >= max_open:
        return False, "max_open_positions"

    # Check daily loss percentage
    daily_loss_pct = risk.get("daily_loss_pct")
    if daily_loss_pct is not None:
        today_str = ts.strftime('%Y-%m-%d')
        equity_df = pd.DataFrame(equity_series)
        equity_df['timestamp'] = pd.to_datetime(equity_df['timestamp'])
        
        # Find the equity at the start of the day
        day_start_equity = equity_df[equity_df['timestamp'].dt.strftime('%Y-%m-%d') < today_str]['equity'].iloc[-1] if not equity_df[equity_df['timestamp'].dt.strftime('%Y-%m-%d') < today_str].empty else initial_equity
        
        current_equity = equity_df['equity'].iloc[-1]
        pnl_pct = (current_equity - day_start_equity) / day_start_equity * 100
        
        if pnl_pct < -daily_loss_pct:
            return False, "daily_loss_pct"

    # TODO: Implement cooldown_minutes
    
    return True, None

def apply_fill_model(side: str, intended_price: float, bar: pd.Series, cfg: ExecutionConfig, tick_size: Decimal) -> float:
    """
    Applies slippage, spread, and latency to an intended price to get the fill price.
    
    Note on Latency: This model currently approximates execution on the *same bar*
    where the signal occurred. A more advanced simulation might delay the fill
    to the open of the *next bar* if a significant latency value is configured.
    # TODO: ceil to next bar if latency_ms > bar_duration
    
    Returns:
        The adjusted fill price.
    """
    fill_price = Decimal(str(intended_price))
    if not cfg:
        return float(fill_price)

    # Apply spread
    if cfg.spread_pips > 0:
        spread_amount = Decimal(str(cfg.spread_pips)) * tick_size
        if side == 'BUY':
            fill_price += spread_amount / 2
        else:
            fill_price -= spread_amount / 2
    
    # Apply slippage
    if cfg.slippage_model == 'FIXED':
        slippage_amount = Decimal(str(cfg.slippage_value)) * tick_size
        fill_price += slippage_amount # Assume worst case
    elif cfg.slippage_model == 'PERCENTAGE':
        slippage_amount = fill_price * (Decimal(str(cfg.slippage_value)) / Decimal('100.0'))
        fill_price += slippage_amount # Assume worst case
            
    return float(fill_price)
