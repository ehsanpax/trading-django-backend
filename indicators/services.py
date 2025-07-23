import pandas as pd
from bots.registry import get_indicator_class
from typing import Dict, Any

class IndicatorService:
    """
    A service to calculate technical indicators on a given DataFrame.
    """

    def calculate_indicator(self, df: pd.DataFrame, indicator_name: str, params: Dict[str, Any]) -> pd.DataFrame:
        """
        Calculates a single technical indicator and adds it to the DataFrame.

        Args:
            df (pd.DataFrame): The input DataFrame with OHLCV data.
            indicator_name (str): The name of the indicator to calculate (e.g., "RSI").
            params (Dict[str, Any]): A dictionary of parameters for the indicator.

        Returns:
            pd.DataFrame: The DataFrame with the added indicator column.
        
        Raises:
            ValueError: If the indicator is not found in the registry.
        """
        indicator_class = get_indicator_class(indicator_name)
        if not indicator_class:
            raise ValueError(f"Indicator '{indicator_name}' not found.")

        indicator_instance = indicator_class()
        return indicator_instance.calculate(df, **params)

    def get_indicator_class(self, indicator_name: str):
        """
        Retrieves an indicator class from the registry by name.
        """
        return get_indicator_class(indicator_name)

    def get_available_indicators(self) -> Dict[str, Any]:
        """
        Retrieves a list of all available indicators and their parameters.

        Returns:
            Dict[str, Any]: A dictionary of available indicators and their metadata.
        """
        from bots.registry import INDICATOR_REGISTRY
        
        indicators_info = {}
        for name, indicator_class in INDICATOR_REGISTRY.items():
            parameters = getattr(indicator_class, 'PARAMETERS', [])
            
            # Convert BotParameter objects to dictionaries
            serialized_params = [
                {
                    "name": p.name,
                    "parameter_type": p.parameter_type,
                    "display_name": p.display_name,
                    "description": p.description,
                    "default_value": p.default_value,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "step": p.step,
                    "options": p.options
                } for p in parameters
            ]
            
            indicators_info[name] = {
                "display_name": getattr(indicator_class, 'DISPLAY_NAME', name),
                "pane_type": getattr(indicator_class, 'PANE_TYPE', 'pane'),
                "scale_type": getattr(indicator_class, 'SCALE_TYPE', 'price'),
                "parameters": serialized_params
            }
        return indicators_info
