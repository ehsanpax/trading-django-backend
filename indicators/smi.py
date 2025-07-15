import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class SMI(BaseIndicator):
    """
    Stochastic Momentum Index (SMI) Indicator.
    A momentum oscillator that ranges from -100 to +100 and is used to identify overbought/oversold conditions.
    """
    NAME = "SMI"
    DISPLAY_NAME = "Stochastic Momentum Index"
    PARAMETERS = [
        BotParameter(
            name="k_period",
            parameter_type="int",
            display_name="%K Period",
            description="The period for the %K calculation.",
            default_value=13,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="d_period",
            parameter_type="int",
            display_name="%D Period",
            description="The period for the %D (signal line) calculation.",
            default_value=2,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="smooth_period",
            parameter_type="int",
            display_name="Smoothing Period",
            description="The smoothing period for the SMI calculation.",
            default_value=2,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="source",
            parameter_type="enum",
            display_name="Source",
            description="The data column to use for calculation (e.g., 'close').",
            default_value="close",
            options=["open", "high", "low", "close"]
        )
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the Stochastic Momentum Index (SMI) and its signal line,
        adding them to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters including 'k_period', 'd_period', 'smooth_period', and 'source'.

        Returns:
            pd.DataFrame: Modified DataFrame with SMI and SMI_Signal columns.
        """
        k_period = params.get("k_period", self.PARAMETERS[0].default_value)
        d_period = params.get("d_period", self.PARAMETERS[1].default_value)
        smooth_period = params.get("smooth_period", self.PARAMETERS[2].default_value)
        source = params.get("source", self.PARAMETERS[3].default_value)

        required_columns = ['high', 'low', source]
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in DataFrame for SMI calculation.")

        min_data_needed = k_period + smooth_period + d_period - 2 # Approximation for required history
        if len(df) < min_data_needed:
            df[f"SMI_{k_period}_{d_period}_{smooth_period}"] = pd.NA
            df[f"SMI_Signal_{k_period}_{d_period}_{smooth_period}"] = pd.NA
            return df

        # Calculate highest high and lowest low over k_period
        lowest_low = df['low'].rolling(window=k_period).min()
        highest_high = df['high'].rolling(window=k_period).max()

        # Calculate %K (Stochastic Oscillator)
        # %K = ((Close - Lowest Low) / (Highest High - Lowest Low)) * 100
        range_hl = highest_high - lowest_low
        range_cl = df[source] - lowest_low

        # Handle division by zero
        smi_numerator = range_cl.ewm(span=smooth_period, adjust=False).mean()
        smi_denominator = range_hl.ewm(span=smooth_period, adjust=False).mean()

        smi = (smi_numerator / smi_denominator) * 100
        smi = smi.fillna(0) # Fill NaN from division by zero

        # Calculate SMI Signal Line (EMA of SMI)
        smi_signal = smi.ewm(span=d_period, adjust=False).mean()

        df[f"SMI_{k_period}_{d_period}_{smooth_period}"] = smi
        df[f"SMI_Signal_{k_period}_{d_period}_{smooth_period}"] = smi_signal
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for SMI calculation.
        This is determined by the sum of k_period, smooth_period, and d_period.
        """
        k_period = params.get("k_period", self.PARAMETERS[0].default_value)
        d_period = params.get("d_period", self.PARAMETERS[1].default_value)
        smooth_period = params.get("smooth_period", self.PARAMETERS[2].default_value)
        # The required history is the maximum of the periods for initial calculations.
        # A common rule of thumb is k_period + smooth_period + d_period - 2 for initial values to stabilize.
        return k_period + smooth_period + d_period - 2

# Register the indicator
register_indicator(SMI.NAME, SMI)

if __name__ == "__main__":
    # Basic local testing for SMI
    print("Running SMI indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25, 22, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27, 25, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27, 24, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23, 20, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26, 24, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26, 23, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460, 470, 480, 490]
    }
    df = pd.DataFrame(data)

    smi_indicator = SMI()

    # Test with default parameters
    df_smi_default = smi_indicator.calculate(df.copy())
    print("\nDataFrame with default SMI (13, 2, 2, source='close'):")
    print(df_smi_default[[f"SMI_13_2_2", f"SMI_Signal_13_2_2"]].tail())

    # Test with custom parameters
    custom_k = 10
    custom_d = 3
    custom_smooth = 3
    df_smi_custom = smi_indicator.calculate(df.copy(), k_period=custom_k, d_period=custom_d, smooth_period=custom_smooth, source="close")
    print(f"\nDataFrame with custom SMI ({custom_k}, {custom_d}, {custom_smooth}, source='close'):")
    print(df_smi_custom[[f"SMI_{custom_k}_{custom_d}_{custom_smooth}", f"SMI_Signal_{custom_k}_{custom_d}_{custom_smooth}"]].tail())

    # Test required history
    print(f"\nRequired history for default SMI: {smi_indicator.required_history()}")
    print(f"Required history for custom SMI ({custom_k}, {custom_d}, {custom_smooth}): {smi_indicator.required_history(k_period=custom_k, d_period=custom_d, smooth_period=custom_smooth)}")

    # Test with insufficient data
    print("\nTesting with insufficient data:")
    df_small = df.head(5)
    df_smi_small = smi_indicator.calculate(df_small.copy())
    print(df_smi_small[[f"SMI_13_2_2", f"SMI_Signal_13_2_2"]])

    # Test with missing required columns
    print("\nTesting with missing required columns:")
    df_no_high = df.drop(columns=['high'])
    try:
        smi_indicator.calculate(df_no_high.copy())
    except ValueError as e:
        print(f"Caught expected error: {e}")
