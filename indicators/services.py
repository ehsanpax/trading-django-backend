import pandas as pd
from core.registry import indicator_registry
from typing import Dict, Any

class IndicatorService:
    """
    A service to calculate technical indicators on a given DataFrame using the new IndicatorInterface.
    """

    def calculate_indicator(self, df: pd.DataFrame, indicator_name: str, params: Dict[str, Any]) -> pd.DataFrame:
        """
        Calculates a single technical indicator and adds its output(s) to the DataFrame.

        Args:
            df (pd.DataFrame): The input DataFrame with OHLCV data.
            indicator_name (str): The name of the indicator to calculate (e.g., "EMAIndicator").
            params (Dict[str, Any]): A dictionary of parameters for the indicator.

        Returns:
            pd.DataFrame: The DataFrame with the added indicator column(s).
        
        Raises:
            ValueError: If the indicator is not found in the registry.
        """
        indicator_class = self.get_indicator_class(indicator_name)
        indicator_instance = indicator_class()
        
        # The new interface returns a dictionary of Series
        indicator_outputs = indicator_instance.compute(df, params)
        
        df_with_indicator = df.copy()
        for output_name, series in indicator_outputs.items():
            # Create a unique column name, e.g., EMAIndicator_ema
            column_name = f"{indicator_name}_{output_name}"
            df_with_indicator[column_name] = series
            
        return df_with_indicator

    def get_indicator_class(self, indicator_name: str):
        """
        Retrieves an indicator class from the registry by name.
        """
        return indicator_registry.get_indicator(indicator_name)

    def get_available_indicators(self) -> Dict[str, Any]:
        """
        Retrieves a list of all available indicators and their parameters from their schema.

        Returns:
            Dict[str, Any]: A dictionary of available indicators and their metadata.
        """
        indicators_info = {}
        all_indicators = indicator_registry.get_all_indicators()
        
        for name, indicator_class in all_indicators.items():
            schema = getattr(indicator_class, 'PARAMS_SCHEMA', {})
            display_name = getattr(indicator_class, 'NAME', name)
            outputs = getattr(indicator_class, 'OUTPUTS', [])
            pane_type = getattr(indicator_class, 'PANE_TYPE', 'overlay')
            scale_type = getattr(indicator_class, 'SCALE_TYPE', 'linear')
            visual_schema = getattr(indicator_class, 'VISUAL_SCHEMA', None)
            visual_defaults = getattr(indicator_class, 'VISUAL_DEFAULTS', None)
            
            indicators_info[name] = {
                "name": name,
                "display_name": display_name,
                "version": getattr(indicator_class, 'VERSION', 0),
                "outputs": outputs,
                "params_schema": schema,
                "pane_type": pane_type,
                "scale_type": scale_type,
                "visual_schema": visual_schema,
                "visual_defaults": visual_defaults,
            }
        return indicators_info
