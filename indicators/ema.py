from typing import Any, List, Dict, Literal, Optional
import pandas as pd
import pandas_ta as ta
import logging

from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

logger = logging.getLogger(__name__)

class EMA(BaseIndicator):
    NAME = "EMA"
    DISPLAY_NAME = "Exponential Moving Average"
    PANE_TYPE = "overlay"
    SCALE_TYPE = "price"
    PARAMETERS = [
        BotParameter(
            name="length",
            parameter_type="int",
            display_name="Period",
            description="The period for the Exponential Moving Average.",
            default_value=20,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="source",
            parameter_type="enum",
            display_name="Source",
            description="The data column to use for EMA calculation (e.g., 'close', 'open', 'high', 'low').",
            default_value="close",
            options=["open", "high", "low", "close"]
        ),
    ]

    def calculate(self, df: pd.DataFrame, length: int, source: str = "close") -> pd.DataFrame:
        """
        Calculates the Exponential Moving Average (EMA) and adds it to the DataFrame.
        The column name will be EMA_length.
        """
        if source not in df.columns:
            logger.error(f"Source column '{source}' not found in DataFrame for EMA calculation.")
            df[f"EMA_{length}"] = pd.NA
            return df
        
        # Ensure the source column is numeric
        df[source] = pd.to_numeric(df[source], errors='coerce')

        # pandas_ta handles NaN values internally, but we should ensure enough data
        if len(df) < length:
            logger.warning(f"Not enough data ({len(df)} bars) for EMA({length}) calculation. Needs at least {length} bars.")
            df[f"EMA_{length}"] = pd.NA
            return df

        try:
            df.ta.ema(length=length, append=True, close=df[source])
        except Exception as e:
            logger.error(f"Error calculating EMA({length}) from source '{source}': {e}", exc_info=True)
            df[f"EMA_{length}"] = pd.NA
        return df

    def required_history(self, length: int, source: str = "close") -> int:
        """
        Returns the minimum number of historical bars required for EMA calculation.
        EMA typically needs 'length' bars to start producing values.
        """
        return length + 1 # Add 1 for the current bar, or a small buffer

# Register the indicator
register_indicator(EMA.NAME, EMA)

if __name__ == "__main__":
    # Example usage for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 26, 28, 27, 30],
        'high': [13, 16, 17, 15, 19, 20, 22, 21, 24, 27, 25, 29, 30, 29, 32],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 24, 26, 25, 28],
        'close': [12, 15, 14, 16, 18, 19, 21, 20, 23, 24, 25, 27, 29, 28, 31],
    }
    df = pd.DataFrame(data, index=pd.to_datetime(pd.date_range(start='2023-01-01', periods=15, freq='D')))

    ema_indicator = EMA()

    # Calculate EMA with default parameters
    df_ema_default = ema_indicator.calculate(df.copy(), length=20) # Pass length explicitly for testing
    print("\nDataFrame with EMA (length=20, source='close'):")
    print(df_ema_default[[f"EMA_20", "close"]].tail())

    # Calculate EMA with custom parameters
    df_ema_custom = ema_indicator.calculate(df.copy(), length=5, source="open")
    print("\nDataFrame with EMA (length=5, source='open'):")
    print(df_ema_custom[[f"EMA_5", "open"]].tail())

    # Test required history
    print(f"\nRequired history for EMA(20): {ema_indicator.required_history(length=20)}")
    print(f"Required history for EMA(5): {ema_indicator.required_history(length=5)}")

    # Test with insufficient data
    df_small = df.iloc[:3]
    df_ema_small = ema_indicator.calculate(df_small.copy(), length=20)
    print("\nDataFrame with EMA (insufficient data):")
    print(df_ema_small[[f"EMA_20", "close"]].tail())
