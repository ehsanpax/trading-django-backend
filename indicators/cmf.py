import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class CMF(BaseIndicator):
    """
    Chaikin Money Flow (CMF) Indicator.
    Measures the amount of Money Flow Volume over a specific period.
    """
    NAME = "CMF"
    DISPLAY_NAME = "Chaikin Money Flow"
    PANE_TYPE = "pane"
    PARAMETERS = [
        BotParameter(
            name="length",
            parameter_type="int",
            display_name="Length",
            description="Number of periods to use for CMF calculation.",
            default_value=20,
            min_value=1,
            max_value=200,
            step=1
        )
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the Chaikin Money Flow (CMF) and adds it to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters including 'length'.

        Returns:
            pd.DataFrame: Modified DataFrame with the CMF column.
        """
        length = params.get("length", self.PARAMETERS[0].default_value)

        required_columns = ['high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in DataFrame for CMF calculation.")

        if len(df) < length:
            df[f"CMF_{length}"] = pd.NA
            return df

        # Calculate Money Flow Multiplier (MFM)
        # MFM = ((Close - Low) - (High - Close)) / (High - Low)
        # Handle division by zero for High - Low
        high_low_diff = df['high'] - df['low']
        mfm = ((df['close'] - df['low']) - (df['high'] - df['close'])) / high_low_diff
        mfm = mfm.fillna(0) # If High == Low, MFM is 0

        # Calculate Money Flow Volume (MFV)
        # MFV = MFM * Volume
        mfv = mfm * df['volume']

        # Calculate CMF
        # CMF = Sum of MFV over 'length' periods / Sum of Volume over 'length' periods
        sum_mfv = mfv.rolling(window=length).sum()
        sum_volume = df['volume'].rolling(window=length).sum()

        cmf = sum_mfv / sum_volume
        cmf = cmf.fillna(0) # Handle division by zero if sum_volume is 0

        df[f"CMF_{length}"] = cmf
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for CMF calculation.
        CMF requires at least 'length' bars.
        """
        length = params.get("length", self.PARAMETERS[0].default_value)
        return length

# Register the indicator
register_indicator(CMF.NAME, CMF)

if __name__ == "__main__":
    # Basic local testing for CMF
    print("Running CMF indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27, 25, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26, 24, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460, 470, 480, 490]
    }
    df = pd.DataFrame(data)

    cmf_indicator = CMF()

    # Test with default parameters
    df_cmf_default = cmf_indicator.calculate(df.copy())
    print("\nDataFrame with default CMF (length=20):")
    print(df_cmf_default[[f"CMF_{cmf_indicator.PARAMETERS[0].default_value}"]].tail())

    # Test with custom parameters
    custom_length = 10
    df_cmf_custom = cmf_indicator.calculate(df.copy(), length=custom_length)
    print(f"\nDataFrame with custom CMF (length={custom_length}):")
    print(df_cmf_custom[[f"CMF_{custom_length}"]].tail())

    # Test required history
    print(f"\nRequired history for default CMF: {cmf_indicator.required_history()}")
    print(f"Required history for custom CMF (length={custom_length}): {cmf_indicator.required_history(length=custom_length)}")

    # Test with insufficient data
    print("\nTesting with insufficient data:")
    df_small = df.head(5)
    df_cmf_small = cmf_indicator.calculate(df_small.copy(), length=20)
    print(df_cmf_small[[f"CMF_{cmf_indicator.PARAMETERS[0].default_value}"]])

    # Test with missing required columns
    print("\nTesting with missing required columns:")
    df_no_high = df.drop(columns=['high'])
    try:
        cmf_indicator.calculate(df_no_high.copy())
    except ValueError as e:
        print(f"Caught expected error: {e}")
