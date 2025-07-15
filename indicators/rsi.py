import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class RSI(BaseIndicator):
    """
    Relative Strength Index (RSI) Indicator.
    Measures the speed and change of price movements.
    """
    NAME = "RSI"
    DISPLAY_NAME = "Relative Strength Index"
    PARAMETERS = [
        BotParameter(
            name="length",
            parameter_type="int",
            display_name="Length",
            description="Number of periods to use for RSI calculation.",
            default_value=14,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="source",
            parameter_type="enum",
            display_name="Source",
            description="The data column to use for calculation (e.g., 'close', 'open', 'high', 'low', 'volume').",
            default_value="close",
            options=["open", "high", "low", "close", "volume"]
        )
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the Relative Strength Index (RSI) and adds it to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters including 'length' and 'source'.

        Returns:
            pd.DataFrame: Modified DataFrame with the RSI column.
        """
        length = params.get("length", self.PARAMETERS[0].default_value)
        source = params.get("source", self.PARAMETERS[1].default_value)

        if source not in df.columns:
            raise ValueError(f"Source column '{source}' not found in DataFrame.")
        if len(df) < length:
            # Not enough data to calculate RSI for the given length
            df[f"RSI_{length}"] = pd.NA
            return df

        # Calculate price changes
        delta = df[source].diff()

        # Separate gains and losses
        gains = delta.mask(delta < 0, 0)
        losses = -delta.mask(delta > 0, 0)

        # Calculate average gains and losses using Exponential Moving Average (EMA)
        avg_gain = gains.ewm(com=length - 1, adjust=False).mean()
        avg_loss = losses.ewm(com=length - 1, adjust=False).mean()

        # Calculate Relative Strength (RS)
        rs = avg_gain / avg_loss

        # Calculate RSI
        rsi = 100 - (100 / (1 + rs))

        df[f"RSI_{length}"] = rsi
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for RSI calculation.
        RSI requires at least 'length' bars for the initial EMA calculation.
        """
        length = params.get("length", self.PARAMETERS[0].default_value)
        return length + 1 # +1 for the initial diff calculation

# Register the indicator
register_indicator(RSI.NAME, RSI)

if __name__ == "__main__":
    # Basic local testing for RSI
    print("Running RSI indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 20, 18, 15, 12, 10, 13, 16, 19, 22],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27, 25, 22, 20, 17, 14, 12, 15, 18, 21, 24],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 18, 16, 13, 10, 8, 11, 14, 17, 20],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26, 24, 21, 19, 16, 13, 11, 14, 17, 20, 23],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290]
    }
    df = pd.DataFrame(data)

    rsi_indicator = RSI()

    # Test with default parameters
    df_rsi_default = rsi_indicator.calculate(df.copy())
    print("\nDataFrame with default RSI (length=14, source='close'):")
    print(df_rsi_default[[f"RSI_{rsi_indicator.PARAMETERS[0].default_value}"]].tail())

    # Test with custom parameters
    custom_length = 7
    df_rsi_custom = rsi_indicator.calculate(df.copy(), length=custom_length, source="close")
    print(f"\nDataFrame with custom RSI (length={custom_length}, source='close'):")
    print(df_rsi_custom[[f"RSI_{custom_length}"]].tail())

    # Test required history
    print(f"\nRequired history for default RSI: {rsi_indicator.required_history()}")
    print(f"Required history for custom RSI (length={custom_length}): {rsi_indicator.required_history(length=custom_length)}")

    # Test with insufficient data
    print("\nTesting with insufficient data:")
    df_small = df.head(5)
    df_rsi_small = rsi_indicator.calculate(df_small.copy(), length=14)
    print(df_rsi_small[[f"RSI_{rsi_indicator.PARAMETERS[0].default_value}"]])

    # Test with missing source column
    print("\nTesting with missing source column:")
    df_no_close = df.drop(columns=['close'])
    try:
        rsi_indicator.calculate(df_no_close.copy(), source="close")
    except ValueError as e:
        print(f"Caught expected error: {e}")
