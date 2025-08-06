import pandas as pd
from dataclasses import dataclass, field
from typing import List, Any, Literal, Optional, Dict
from bots.registry import get_indicator_class
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

class BaseIndicator:
    """
    Base class for all reusable indicators.
    Indicators should define their parameters using a list of BotParameter instances.
    """
    NAME: str = "BaseIndicator"
    DISPLAY_NAME: str = "Base Indicator"
    PANE_TYPE: str = "pane"  # Default to 'pane', can be 'overlay'
    PARAMETERS: List[BotParameter] = field(default_factory=list)

    def calculate(self, data: Any, **params) -> Any:
        """
        Calculates the indicator value(s) based on input data and parameters.
        This method must be implemented by subclasses.
        """
        raise NotImplementedError("calculate method must be implemented by subclasses")

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars/data points required
        to calculate this indicator with the given parameters.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("required_history method must be implemented by subclasses")

class BaseStrategy:
    """
    Base class for all trading strategies.
    Strategies should define their parameters and declare required indicators.
    """
    NAME: str = "BaseStrategy"
    DISPLAY_NAME: str = "Base Strategy"
    PARAMETERS: List[BotParameter] = field(default_factory=list)
    REQUIRED_INDICATORS: List[Dict[str, Any]] = field(default_factory=list) # e.g., [{"name": "EMA", "params": {"period": 20}}]

    def __init__(self, instrument_symbol: str, account_id: str, instrument_spec: Any, strategy_params: Dict[str, Any], indicator_params: Dict[str, Any], risk_settings: Dict[str, Any]):
        self.instrument_symbol = instrument_symbol
        self.account_id = account_id
        self.instrument_spec = instrument_spec
        self.strategy_params = strategy_params
        self.indicator_params = indicator_params # Parameters for indicators used by this strategy
        self.risk_settings = risk_settings

    def run_tick(self, df_current_window: Any, account_equity: float) -> List[Dict[str, Any]]:
        """
        Executes the strategy logic for the current tick/bar.
        This method must be implemented by subclasses.
        Returns a list of actions (e.g., trade signals).
        """
        raise NotImplementedError("run_tick method must be implemented by subclasses")

    def get_min_bars_needed(self, buffer_bars: int = 10) -> int:
        """
        Calculates the minimum number of bars required for the strategy,
        considering its own parameters and required indicators.
        This method should be implemented by subclasses.
        """
        raise NotImplementedError("get_min_bars_needed method must be implemented by subclasses")

    def get_indicator_column_names(self) -> List[str]:
        """
        Returns a list of column names for the indicators used by the strategy.
        This can be overridden by subclasses if they generate columns with dynamic names.
        """
        column_names = []
        for ind_config in self.REQUIRED_INDICATORS:
            indicator_name = ind_config["name"]
            indicator_params = ind_config.get("params", {})
            
            # Resolve any dynamic parameters (e.g., referencing a strategy parameter)
            resolved_params = {}
            for key, value in indicator_params.items():
                if isinstance(value, str) and value in self.strategy_params:
                    resolved_params[key] = self.strategy_params[value]
                else:
                    resolved_params[key] = value
            
            # This logic should align with how indicators name their columns.
            # Most pandas_ta indicators name columns like "EMA_20", "ATR_14", etc.
            if 'length' in resolved_params:
                column_names.append(f"{indicator_name}_{resolved_params['length']}")
            elif indicator_name == "ATR": # ATR has a specific naming convention in pandas_ta
                column_names.append(f"ATRr_{resolved_params.get('length', 14)}") # Default to 14 if not specified
            else:
                column_names.append(indicator_name)
            
        return column_names

    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensures that all required indicators are calculated and present in the DataFrame.
        This method iterates through REQUIRED_INDICATORS, calculates them, and adds them as columns.
        """
        df_copy = df.copy()
        for ind_config in self.REQUIRED_INDICATORS:
            indicator_name = ind_config["name"]
            indicator_params = ind_config.get("params", {})
            
            # Resolve any dynamic parameters (e.g., referencing a strategy parameter)
            resolved_params = {}
            for key, value in indicator_params.items():
                if isinstance(value, str) and value in self.strategy_params:
                    resolved_params[key] = self.strategy_params[value]
                else:
                    resolved_params[key] = value
            
            indicator_cls = get_indicator_class(indicator_name)
            if not indicator_cls:
                logger.warning(f"Indicator '{indicator_name}' not found in registry. Skipping.")
                continue
            
            indicator_instance = indicator_cls()
            
            try:
                # The calculate method is expected to return a modified DataFrame
                df_copy = indicator_instance.calculate(df_copy, **resolved_params)
            except Exception as e:
                logger.error(f"Error calculating indicator '{indicator_name}' with params {resolved_params}: {e}", exc_info=True)
                # Depending on strictness, you might want to raise the exception
                # For now, we'll just add a column of NaNs to avoid breaking the whole process
                df_copy[column_name] = pd.NA

        return df_copy
