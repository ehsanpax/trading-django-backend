import pandas as pd
from dataclasses import dataclass, field
from typing import List, Any, Literal, Optional, Dict
import logging

logger = logging.getLogger(__name__)

@dataclass
class BotParameter:
    name: str
    parameter_type: Literal["int", "float", "str", "bool", "enum"]
    display_name: str
    description: str
    default_value: Any
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    step: Optional[Any] = None
    options: Optional[List[Any]] = None # For enum types

class BaseStrategy:
    """
    Base class for all trading strategies.
    Strategies should define their parameters and declare required indicators.
    """
    NAME: str = "BaseStrategy"
    DISPLAY_NAME: str = "Base Strategy"
    PARAMETERS: List[BotParameter] = []
    REQUIRED_INDICATORS: List[Dict[str, Any]] = []

    def __init__(self, instrument_symbol: str, account_id: str, instrument_spec: Any, strategy_params: Dict[str, Any], indicator_params: Dict[str, Any], risk_settings: Dict[str, Any]):
        self.instrument_symbol = instrument_symbol
        self.account_id = account_id
        self.instrument_spec = instrument_spec
        self.strategy_params = strategy_params
        self.indicator_params = indicator_params
        self.risk_settings = risk_settings
        self.df = None # The strategy will hold the dataframe with indicators

    def run_tick(self, df_current_window: Any, account_equity: float) -> List[Dict[str, Any]]:
        """
        Executes the strategy logic for the current tick/bar.
        This method must be implemented by subclasses.
        Returns a list of actions.

        Allowed Actions & Schemas:
        - OPEN_TRADE: {"action": "OPEN_TRADE", "side": "BUY"|"SELL", "qty": float, "sl": float|None, "tp": float|None, "tag": str|None}
        - CLOSE_POSITION: {"action": "CLOSE_POSITION", "side": "BUY"|"SELL"|"ANY", "qty": "ALL"|float, "tag": str|None}
        - REDUCE_POSITION: {"action": "REDUCE_POSITION", "side": "BUY"|"SELL", "qty": float, "tag": str|None}
        - MODIFY_SLTP: {"action": "MODIFY_SLTP", "side": "BUY"|"SELL"|"ANY", "sl": float|None, "tp": float|None, "tag": str|None}
        """
        raise NotImplementedError("run_tick method must be implemented by subclasses")

    def get_min_bars_needed(self, buffer_bars: int = 10) -> int:
        """
        Calculates the minimum number of bars required for the strategy.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("get_min_bars_needed method must be implemented by subclasses")

    def get_indicator_column_names(self) -> List[str]:
        """
        Returns a list of column names for the indicators used by the strategy.
        """
        # This method will likely be deprecated or changed as the engine evolves.
        # For now, it's not directly used by the new engine flow.
        return []

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates all required indicators and adds them to the DataFrame.
        """
        from core.registry import indicator_registry
        df_copy = df.copy()
        for ind_config in self.REQUIRED_INDICATORS:
            indicator_name = ind_config["name"]
            indicator_params = ind_config.get("params", {})
            
            resolved_params = {}
            for key, value in indicator_params.items():
                if isinstance(value, str) and value in self.strategy_params:
                    resolved_params[key] = self.strategy_params[value]
                else:
                    resolved_params[key] = value
            
            try:
                indicator_cls = indicator_registry.get_indicator(indicator_name)
                indicator_instance = indicator_cls()

                # Merge PARAMS_SCHEMA defaults so omitted params (e.g., source) get sensible defaults
                default_params: Dict[str, Any] = {}
                try:
                    schema = getattr(indicator_cls, 'PARAMS_SCHEMA', {}) or {}
                    for p_name, p_schema in schema.items():
                        if p_schema is None:
                            continue
                        default_val = p_schema.get('default')
                        if default_val is not None:
                            default_params[p_name] = default_val
                except Exception:
                    # If schema probing fails, proceed with provided params only
                    pass
                # Provided params override defaults
                resolved_params = {**default_params, **resolved_params}

                indicator_outputs = indicator_instance.compute(df_copy, resolved_params)
                for output_name, series in indicator_outputs.items():
                    # Create a unique column name to avoid collisions
                    param_str = "_".join([f"{k}_{v}" for k, v in sorted(resolved_params.items())])
                    column_name = f"{indicator_name}_{output_name}_{param_str}"
                    df_copy[column_name] = series
            except Exception as e:
                logger.error(f"Error calculating indicator '{indicator_name}': {e}", exc_info=True)

        return df_copy


# --- Action Helper Functions ---

<<<<<<< Updated upstream
def make_open_trade(side: Literal["BUY", "SELL"], qty: float, sl: Optional[float] = None, tp: Optional[float] = None, tag: Optional[str] = None, risk_percent: Optional[float] = None) -> Dict[str, Any]:
=======
def make_open_trade(side: Literal["BUY", "SELL"], qty: float, sl: Optional[float] = None, tp: Optional[float] = None, tag: Optional[str] = None) -> Dict[str, Any]:
>>>>>>> Stashed changes
    """Creates and validates an OPEN_TRADE action."""
    if qty <= 0:
        raise ValueError("Quantity for opening a trade must be positive.")
    if side not in ["BUY", "SELL"]:
        raise ValueError("Side must be 'BUY' or 'SELL'.")
<<<<<<< Updated upstream
    
    action = {
=======
    return {
>>>>>>> Stashed changes
        "action": "OPEN_TRADE",
        "side": side,
        "qty": qty,
        "sl": sl,
        "tp": tp,
        "tag": tag,
    }
<<<<<<< Updated upstream
    if risk_percent is not None:
        action["risk_percent"] = risk_percent
        
    return action
=======
>>>>>>> Stashed changes

def make_close_position(side: Literal["BUY", "SELL", "ANY"] = "ANY", qty: Literal["ALL"] | float = "ALL", tag: Optional[str] = None) -> Dict[str, Any]:
    """Creates and validates a CLOSE_POSITION action."""
    if isinstance(qty, (int, float)) and qty <= 0:
        raise ValueError("Quantity for closing a position must be positive.")
    if side not in ["BUY", "SELL", "ANY"]:
        raise ValueError("Side must be 'BUY', 'SELL', or 'ANY'.")
    return {
        "action": "CLOSE_POSITION",
        "side": side,
        "qty": qty,
        "tag": tag,
    }

def make_reduce_position(side: Literal["BUY", "SELL"], qty: float, tag: Optional[str] = None) -> Dict[str, Any]:
    """Creates and validates a REDUCE_POSITION action."""
    if qty <= 0:
        raise ValueError("Quantity for reducing a position must be positive.")
    if side not in ["BUY", "SELL"]:
        raise ValueError("Side must be 'BUY' or 'SELL'.")
    return {
        "action": "REDUCE_POSITION",
        "side": side,
        "qty": qty,
        "tag": tag,
    }

def make_modify_sltp(side: Literal["BUY", "SELL", "ANY"] = "ANY", sl: Optional[float] = None, tp: Optional[float] = None, tag: Optional[str] = None) -> Dict[str, Any]:
    """Creates and validates a MODIFY_SLTP action."""
    if sl is None and tp is None:
        raise ValueError("At least one of 'sl' or 'tp' must be provided for modification.")
    if side not in ["BUY", "SELL", "ANY"]:
        raise ValueError("Side must be 'BUY', 'SELL', or 'ANY'.")
    return {
        "action": "MODIFY_SLTP",
        "side": side,
        "sl": sl,
        "tp": tp,
        "tag": tag,
    }
