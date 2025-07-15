from typing import Any, List, Dict, Literal, Optional
import pandas as pd
import pandas_ta as ta
import logging

from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

logger = logging.getLogger(__name__)

class ATR(BaseIndicator):
    NAME = "ATR"
    DISPLAY_NAME = "Average True Range"
    PARAMETERS = [
        BotParameter(
            name="length",
            parameter_type="int",
            display_name="Period",
            description="The period for the Average True Range calculation.",
            default_value=14,
            min_value=1,
            max_value=100,
            step=1
        ),
    ]

    def calculate(self, df: pd.DataFrame, length: int) -> pd.DataFrame:
        """
        Calculates the Average True Range (ATR) and adds it to the DataFrame.
        The column name will be ATRr_length.
        """
        required_ohlcv = ["high", "low", "close"]
        for col in required_ohlcv:
            if col not in df.columns:
                logger.error(f"Missing required column '{col}' for ATR calculation.")
                df[f"ATRr_{length}"] = pd.NA
                return df
            df[col] = pd.to_numeric(df[col], errors='coerce')

        if len(df) < length:
            logger.warning(f"Not enough data ({len(df)} bars) for ATR({length}) calculation. Needs at least {length} bars.")
            df[f"ATRr_{length}"] = pd.NA
            return df

        try:
            df.ta.atr(length=length, append=True)
        except Exception as e:
            logger.error(f"Error calculating ATR({length}): {e}", exc_info=True)
            df[f"ATRr_{length}"] = pd.NA
        return df

    def required_history(self, length: int) -> int:
        """
        Returns the minimum number of historical bars required for ATR calculation.
        ATR typically needs 'length' bars to start producing values.
        """
        return length + 1 # Add 1 for the current bar, or a small buffer

# Register the indicator
register_indicator(ATR.NAME, ATR)

if __name__ == "__main__":
    # Example usage for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 26, 28, 27, 30],
        'high': [13, 16, 17, 15, 19, 20, 22, 21, 24, 27, 25, 29, 30, 29, 32],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 24, 26, 28, 25, 28], # Corrected a typo here
        'close': [12, 15, 14, 16, 18, 19, 21, 20, 23, 24, 25, 27, 29, 28, 31],
    }
    df = pd.DataFrame(data, index=pd.to_datetime(pd.date_range(start='2023-01-01', periods=15, freq='D')))

    atr_indicator = ATR()

    # Calculate ATR with default parameters
    df_atr_default = atr_indicator.calculate(df.copy(), length=14) # Pass length explicitly for testing
    print("\nDataFrame with ATR (length=14):")
    print(df_atr_default[[f"ATRr_14", "close"]].tail())

    # Calculate ATR with custom parameters
    df_atr_custom = atr_indicator.calculate(df.copy(), length=5)
    print("\nDataFrame with ATR (length=5):")
    print(df_atr_custom[[f"ATRr_5", "close"]].tail())

    # Test required history
    print(f"\nRequired history for ATR(14): {atr_indicator.required_history(length=14)}")
    print(f"Required history for ATR(5): {atr_indicator.required_history(length=5)}")

    # Test with insufficient data
    df_small = df.iloc[:3]
    df_atr_small = atr_indicator.calculate(df_small.copy(), length=14)
    print("\nDataFrame with ATR (insufficient data):")
    print(df_atr_small[[f"ATRr_14", "close"]].tail())
