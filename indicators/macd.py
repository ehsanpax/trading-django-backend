import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class MACD(BaseIndicator):
    """
    Moving Average Convergence Divergence (MACD) Indicator.
    A trend-following momentum indicator that shows the relationship between two moving averages of a security’s price.
    """
    NAME = "MACD"
    DISPLAY_NAME = "Moving Average Convergence Divergence"
    PARAMETERS = [
        BotParameter(
            name="fast_period",
            parameter_type="int",
            display_name="Fast Period",
            description="The period for the fast Exponential Moving Average (EMA).",
            default_value=12,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="slow_period",
            parameter_type="int",
            display_name="Slow Period",
            description="The period for the slow Exponential Moving Average (EMA).",
            default_value=26,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="signal_period",
            parameter_type="int",
            display_name="Signal Period",
            description="The period for the Signal Line EMA.",
            default_value=9,
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
        Calculates the MACD, Signal Line, and MACD Histogram and adds them to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters including 'fast_period', 'slow_period', 'signal_period', and 'source'.

        Returns:
            pd.DataFrame: Modified DataFrame with MACD, Signal Line, and Histogram columns.
        """
        fast_period = params.get("fast_period", self.PARAMETERS[0].default_value)
        slow_period = params.get("slow_period", self.PARAMETERS[1].default_value)
        signal_period = params.get("signal_period", self.PARAMETERS[2].default_value)
        source = params.get("source", self.PARAMETERS[3].default_value)

        if source not in df.columns:
            raise ValueError(f"Source column '{source}' not found in DataFrame.")

        # Ensure slow_period is greater than fast_period
        if fast_period >= slow_period:
            raise ValueError("Fast period must be less than slow period for MACD calculation.")

        # Check for sufficient data
        min_data_needed = max(fast_period, slow_period) + signal_period - 1 # For initial EMA calculations
        if len(df) < min_data_needed:
            df[f"MACD_{fast_period}_{slow_period}_{signal_period}"] = pd.NA
            df[f"MACD_Signal_{fast_period}_{slow_period}_{signal_period}"] = pd.NA
            df[f"MACD_Hist_{fast_period}_{slow_period}_{signal_period}"] = pd.NA
            return df

        # Calculate Fast EMA
        fast_ema = df[source].ewm(span=fast_period, adjust=False).mean()

        # Calculate Slow EMA
        slow_ema = df[source].ewm(span=slow_period, adjust=False).mean()

        # Calculate MACD Line
        macd_line = fast_ema - slow_ema

        # Calculate Signal Line (EMA of MACD Line)
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

        # Calculate MACD Histogram
        macd_histogram = macd_line - signal_line

        df[f"MACD_{fast_period}_{slow_period}_{signal_period}"] = macd_line
        df[f"MACD_Signal_{fast_period}_{slow_period}_{signal_period}"] = signal_line
        df[f"MACD_Hist_{fast_period}_{slow_period}_{signal_period}"] = macd_histogram
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for MACD calculation.
        This is determined by the longest period among fast, slow, and signal periods.
        """
        fast_period = params.get("fast_period", self.PARAMETERS[0].default_value)
        slow_period = params.get("slow_period", self.PARAMETERS[1].default_value)
        signal_period = params.get("signal_period", self.PARAMETERS[2].default_value)
        # The required history is the maximum of the periods, plus the signal period for its EMA calculation.
        # A common rule of thumb is max(fast, slow) + signal - 1 for initial values to stabilize.
        return max(fast_period, slow_period) + signal_period - 1

# Register the indicator
register_indicator(MACD.NAME, MACD)

if __name__ == "__main__":
    # Basic local testing for MACD
    print("Running MACD indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25, 22, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27, 25, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27, 24, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23, 20, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26, 24, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26, 23, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460, 470, 480, 490]
    }
    df = pd.DataFrame(data)

    macd_indicator = MACD()

    # Test with default parameters
    df_macd_default = macd_indicator.calculate(df.copy())
    print("\nDataFrame with default MACD (12, 26, 9, source='close'):")
    print(df_macd_default[[f"MACD_12_26_9", f"MACD_Signal_12_26_9", f"MACD_Hist_12_26_9"]].tail())

    # Test with custom parameters
    custom_fast = 8
    custom_slow = 17
    custom_signal = 9
    df_macd_custom = macd_indicator.calculate(df.copy(), fast_period=custom_fast, slow_period=custom_slow, signal_period=custom_signal, source="close")
    print(f"\nDataFrame with custom MACD ({custom_fast}, {custom_slow}, {custom_signal}, source='close'):")
    print(df_macd_custom[[f"MACD_{custom_fast}_{custom_slow}_{custom_signal}", f"MACD_Signal_{custom_fast}_{custom_slow}_{custom_signal}", f"MACD_Hist_{custom_fast}_{custom_slow}_{custom_signal}"]].tail())

    # Test required history
    print(f"\nRequired history for default MACD: {macd_indicator.required_history()}")
    print(f"Required history for custom MACD ({custom_fast}, {custom_slow}, {custom_signal}): {macd_indicator.required_history(fast_period=custom_fast, slow_period=custom_slow, signal_period=custom_signal)}")

    # Test with insufficient data
    print("\nTesting with insufficient data:")
    df_small = df.head(10) # Should be less than required history for default (12+26+9-1 = 46-1 = 45)
    df_macd_small = macd_indicator.calculate(df_small.copy())
    print(df_macd_small[[f"MACD_12_26_9", f"MACD_Signal_12_26_9", f"MACD_Hist_12_26_9"]])

    # Test with missing source column
    print("\nTesting with missing source column:")
    df_no_close = df.drop(columns=['close'])
    try:
        macd_indicator.calculate(df_no_close.copy(), source="close")
    except ValueError as e:
        print(f"Caught expected error: {e}")

    # Test with fast_period >= slow_period
    print("\nTesting with fast_period >= slow_period:")
    try:
        macd_indicator.calculate(df.copy(), fast_period=26, slow_period=26, signal_period=9)
    except ValueError as e:
        print(f"Caught expected error: {e}")
