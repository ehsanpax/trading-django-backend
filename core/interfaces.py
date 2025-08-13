import pandas as pd
from typing import Dict, List, Protocol, runtime_checkable
from collections import namedtuple

IndicatorRequest = namedtuple('IndicatorRequest', ['name', 'params'])

class IndicatorInterface(Protocol):
    """
    A formal contract for all indicators.
    """
    VERSION: int
    PANE_TYPE: str
    OUTPUTS: List[str]
    PARAMS_SCHEMA: Dict

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Computes the indicator values.

        This method must be a pure function, meaning for the same ohlcv and params,
        it must always return the same output. It should not have side effects.

        Args:
            ohlcv (pd.DataFrame): DataFrame with columns 'open', 'high', 'low', 'close', 'volume'.
            params (Dict): A dictionary of parameters validated against PARAMS_SCHEMA.

        Returns:
            Dict[str, pd.Series]: A dictionary where keys are from OUTPUTS and values are the computed Series.
        """
        ...


class StrategyInterface(Protocol):
    """
    A formal contract for all strategies compatible with the event-driven engine.
    """

    def on_bar_close(self, ohlcv: pd.DataFrame) -> List[Dict]:
        """
        Called by the engine on each bar close.
        
        Returns:
            A list of action dictionaries.
        """
        ...


@runtime_checkable
class OperatorInterface(Protocol):
    """
    A formal contract for all logic operators in the no-code builder.
    """
    VERSION: int
    PARAMS_SCHEMA: Dict

    def compute(self, *args) -> bool | float:
        """
        Computes the operator's logic.
        """
        ...


@runtime_checkable
class ActionInterface(Protocol):
    """
    A formal contract for all actions in the no-code builder.
    """
    VERSION: int
    PARAMS_SCHEMA: Dict

    def execute(self, *args):
        """
        Executes the action.
        """
        ...
