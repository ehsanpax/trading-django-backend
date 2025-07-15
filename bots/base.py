from dataclasses import dataclass, field
from typing import List, Any, Literal, Optional, Dict

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
