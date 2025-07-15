import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class DMI(BaseIndicator):
    """
    Directional Movement Index (DMI) Indicator.
    Measures the strength of price movement in positive and negative directions.
    Consists of +DI, -DI, and ADX.
    """
    NAME = "DMI"
    DISPLAY_NAME = "Directional Movement Index"
    PARAMETERS = [
        BotParameter(
            name="length",
            parameter_type="int",
            display_name="Length",
            description="Number of periods to use for DI and ADX calculation.",
            default_value=14,
            min_value=1,
            max_value=200,
            step=1
        )
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the Directional Movement Index (+DI, -DI, ADX) and adds them to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters including 'length'.

        Returns:
            pd.DataFrame: Modified DataFrame with +DI, -DI, and ADX columns.
        """
        length = params.get("length", self.PARAMETERS[0].default_value)

        required_columns = ['high', 'low', 'close']
        for col in required_columns:
            if col not in df.columns:
                raise ValueError(f"Required column '{col}' not found in DataFrame for DMI calculation.")

        if len(df) < length + 1: # Need at least length + 1 for initial calculations
            df[f"DMI_PlusDI_{length}"] = pd.NA
            df[f"DMI_MinusDI_{length}"] = pd.NA
            df[f"DMI_ADX_{length}"] = pd.NA
            return df

        # Calculate Directional Movement (DM)
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        # Apply conditions for DM
        true_range = df[['high', 'low', 'close']].apply(lambda x: max(x['high'] - x['low'], abs(x['high'] - x['close']), abs(x['low'] - x['close'])), axis=1)

        # Calculate True Range (TR)
        # TR = max(High - Low, abs(High - Previous Close), abs(Low - Previous Close))
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift(1))
        tr3 = abs(df['low'] - df['close'].shift(1))
        tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)

        # Smooth DM and TR using Wilder's Smoothing (similar to EMA with alpha = 1/length)
        # ATR is the smoothed True Range
        atr = tr.ewm(alpha=1/length, adjust=False).mean()

        plus_dm_smooth = plus_dm.ewm(alpha=1/length, adjust=False).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=1/length, adjust=False).mean()

        # Calculate Directional Indicators (+DI and -DI)
        plus_di = (plus_dm_smooth / atr) * 100
        minus_di = (minus_dm_smooth / atr) * 100

        # Calculate Directional Movement Index (DX)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        dx = dx.fillna(0) # Handle division by zero if plus_di + minus_di is 0

        # Calculate Average Directional Index (ADX)
        adx = dx.ewm(alpha=1/length, adjust=False).mean()

        df[f"DMI_PlusDI_{length}"] = plus_di
        df[f"DMI_MinusDI_{length}"] = minus_di
        df[f"DMI_ADX_{length}"] = adx
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for DMI calculation.
        DMI requires at least 'length' bars for smoothing, plus 1 for initial diff.
        """
        length = params.get("length", self.PARAMETERS[0].default_value)
        return length + 1

# Register the indicator
register_indicator(DMI.NAME, DMI)

if __name__ == "__main__":
    # Basic local testing for DMI
    print("Running DMI indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25, 22, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27, 25, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27, 24, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23, 20, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26, 24, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26, 23, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460, 470, 480, 490]
    }
    df = pd.DataFrame(data)

    dmi_indicator = DMI()

    # Test with default parameters
    df_dmi_default = dmi_indicator.calculate(df.copy())
    print("\nDataFrame with default DMI (length=14):")
    print(df_dmi_default[[f"DMI_PlusDI_14", f"DMI_MinusDI_14", f"DMI_ADX_14"]].tail())

    # Test with custom parameters
    custom_length = 7
    df_dmi_custom = dmi_indicator.calculate(df.copy(), length=custom_length)
    print(f"\nDataFrame with custom DMI (length={custom_length}):")
    print(df_dmi_custom[[f"DMI_PlusDI_{custom_length}", f"DMI_MinusDI_{custom_length}", f"DMI_ADX_{custom_length}"]].tail())

    # Test required history
    print(f"\nRequired history for default DMI: {dmi_indicator.required_history()}")
    print(f"Required history for custom DMI (length={custom_length}): {dmi_indicator.required_history(length=custom_length)}")

    # Test with insufficient data
    print("\nTesting with insufficient data:")
    df_small = df.head(5)
    df_dmi_small = dmi_indicator.calculate(df_small.copy(), length=14)
    print(df_dmi_small[[f"DMI_PlusDI_14", f"DMI_MinusDI_14", f"DMI_ADX_14"]])

    # Test with missing required columns
    print("\nTesting with missing required columns:")
    df_no_high = df.drop(columns=['high'])
    try:
        dmi_indicator.calculate(df_no_high.copy())
    except ValueError as e:
        print(f"Caught expected error: {e}")
