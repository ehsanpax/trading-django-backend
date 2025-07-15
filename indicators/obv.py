import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class OBV(BaseIndicator):
    """
    On-Balance Volume (OBV) Indicator.
    Measures buying and selling pressure as a cumulative total volume.
    """
    NAME = "OBV"
    DISPLAY_NAME = "On-Balance Volume"
    PARAMETERS = [
        BotParameter(
            name="source_close",
            parameter_type="enum",
            display_name="Source (Close)",
            description="The data column to use for close price (e.g., 'close').",
            default_value="close",
            options=["open", "high", "low", "close"]
        ),
        BotParameter(
            name="source_volume",
            parameter_type="enum",
            display_name="Source (Volume)",
            description="The data column to use for volume (e.g., 'volume').",
            default_value="volume",
            options=["volume"]
        )
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the On-Balance Volume (OBV) and adds it to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters including 'source_close' and 'source_volume'.

        Returns:
            pd.DataFrame: Modified DataFrame with the OBV column.
        """
        source_close = params.get("source_close", self.PARAMETERS[0].default_value)
        source_volume = params.get("source_volume", self.PARAMETERS[1].default_value)

        required_columns = [source_close, source_volume]
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in DataFrame for OBV calculation.")

        obv = pd.Series(0, index=df.index, dtype=float)
        if len(df) > 0:
            obv.iloc[0] = 0 # Initialize first OBV value to 0 or first volume

            for i in range(1, len(df)):
                if df[source_close].iloc[i] > df[source_close].iloc[i-1]:
                    obv.iloc[i] = obv.iloc[i-1] + df[source_volume].iloc[i]
                elif df[source_close].iloc[i] < df[source_close].iloc[i-1]:
                    obv.iloc[i] = obv.iloc[i-1] - df[source_volume].iloc[i]
                else:
                    obv.iloc[i] = obv.iloc[i-1]

        df[f"OBV"] = obv
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for OBV calculation.
        OBV requires at least 2 bars to calculate the first change.
        """
        return 2

# Register the indicator
register_indicator(OBV.NAME, OBV)

if __name__ == "__main__":
    # Basic local testing for OBV
    print("Running OBV indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190]
    }
    df = pd.DataFrame(data)

    obv_indicator = OBV()

    # Test with default parameters
    df_obv_default = obv_indicator.calculate(df.copy())
    print("\nDataFrame with default OBV:")
    print(df_obv_default[[f"OBV"]].tail())

    # Test required history
    print(f"\nRequired history for OBV: {obv_indicator.required_history()}")

    # Test with insufficient data
    print("\nTesting with insufficient data (1 bar):")
    df_small = df.head(1)
    df_obv_small = obv_indicator.calculate(df_small.copy())
    print(df_obv_small[[f"OBV"]])

    # Test with missing required columns
    print("\nTesting with missing required columns:")
    df_no_close = df.drop(columns=['close'])
    try:
        obv_indicator.calculate(df_no_close.copy())
    except ValueError as e:
        print(f"Caught expected error: {e}")
