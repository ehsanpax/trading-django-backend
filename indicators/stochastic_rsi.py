import pandas as pd
from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

class StochasticRSI(BaseIndicator):
    """
    Stochastic RSI Indicator.
    An oscillator that measures the level of RSI relative to its high-low range over a set period.
    """
    NAME = "StochasticRSI"
    DISPLAY_NAME = "Stochastic Relative Strength Index"
    PARAMETERS = [
        BotParameter(
            name="rsi_length",
            parameter_type="int",
            display_name="RSI Length",
            description="Number of periods to use for the initial RSI calculation.",
            default_value=14,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="stoch_length",
            parameter_type="int",
            display_name="Stochastic Length",
            description="Number of periods to use for the Stochastic calculation on RSI.",
            default_value=14,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="k_period",
            parameter_type="int",
            display_name="%K Period",
            description="Smoothing period for %K line.",
            default_value=3,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="d_period",
            parameter_type="int",
            display_name="%D Period",
            description="Smoothing period for %D line (signal line).",
            default_value=3,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="source",
            parameter_type="enum",
            display_name="Source",
            description="The data column to use for initial RSI calculation (e.g., 'close').",
            default_value="close",
            options=["open", "high", "low", "close", "volume"]
        )
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the Stochastic RSI (%K and %D lines) and adds them to the DataFrame.

        Args:
            df (pd.DataFrame): Input DataFrame with OHLCV data.
            **params: Dictionary of parameters.

        Returns:
            pd.DataFrame: Modified DataFrame with Stochastic RSI %K and %D columns.
        """
        rsi_length = params.get("rsi_length", self.PARAMETERS[0].default_value)
        stoch_length = params.get("stoch_length", self.PARAMETERS[1].default_value)
        k_period = params.get("k_period", self.PARAMETERS[2].default_value)
        d_period = params.get("d_period", self.PARAMETERS[3].default_value)
        source = params.get("source", self.PARAMETERS[4].default_value)

        if source not in df.columns:
            raise ValueError(f"Source column '{source}' not found in DataFrame.")

        # Calculate initial RSI
        delta = df[source].diff()
        gains = delta.mask(delta < 0, 0)
        losses = -delta.mask(delta > 0, 0)
        avg_gain = gains.ewm(com=rsi_length - 1, adjust=False).mean()
        avg_loss = losses.ewm(com=rsi_length - 1, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # Check for sufficient data after RSI calculation
        min_data_needed = rsi_length + stoch_length + k_period + d_period - 3 # Approximation
        if len(df) < min_data_needed:
            df[f"StochRSI_K_{rsi_length}_{stoch_length}_{k_period}_{d_period}"] = pd.NA
            df[f"StochRSI_D_{rsi_length}_{stoch_length}_{k_period}_{d_period}"] = pd.NA
            return df

        # Calculate highest RSI and lowest RSI over stoch_length
        lowest_rsi = rsi.rolling(window=stoch_length).min()
        highest_rsi = rsi.rolling(window=stoch_length).max()

        # Calculate Stochastic RSI %K
        # StochRSI = ((RSI - Lowest RSI) / (Highest RSI - Lowest RSI)) * 100
        stoch_rsi_k = ((rsi - lowest_rsi) / (highest_rsi - lowest_rsi)) * 100
        stoch_rsi_k = stoch_rsi_k.fillna(0) # Handle division by zero

        # Smooth %K
        stoch_rsi_k_smoothed = stoch_rsi_k.rolling(window=k_period).mean()

        # Calculate Stochastic RSI %D (signal line)
        stoch_rsi_d = stoch_rsi_k_smoothed.rolling(window=d_period).mean()

        df[f"StochRSI_K_{rsi_length}_{stoch_length}_{k_period}_{d_period}"] = stoch_rsi_k_smoothed
        df[f"StochRSI_D_{rsi_length}_{stoch_length}_{k_period}_{d_period}"] = stoch_rsi_d
        return df

    def required_history(self, **params) -> int:
        """
        Returns the minimum number of historical bars required for Stochastic RSI calculation.
        This is determined by the sum of rsi_length, stoch_length, k_period, and d_period.
        """
        rsi_length = params.get("rsi_length", self.PARAMETERS[0].default_value)
        stoch_length = params.get("stoch_length", self.PARAMETERS[1].default_value)
        k_period = params.get("k_period", self.PARAMETERS[2].default_value)
        d_period = params.get("d_period", self.PARAMETERS[3].default_value)
        # The required history is the sum of all periods for initial values to stabilize.
        return rsi_length + stoch_length + k_period + d_period - 3

# Register the indicator
register_indicator(StochasticRSI.NAME, StochasticRSI)

if __name__ == "__main__":
    # Basic local testing for Stochastic RSI
    print("Running Stochastic RSI indicator test...")
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25, 22, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25, 22, 20, 18, 15, 12, 10, 13, 16, 19, 22, 25, 28, 30, 28, 25, 22, 20, 18, 15, 12],
        'high': [12, 15, 17, 15, 18, 20, 22, 21, 24, 27, 25, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27, 24, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27, 24, 22, 20, 17, 14, 12, 15, 18, 21, 24, 27, 30, 32, 30, 27, 24, 22, 20, 17, 14],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23, 20, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23, 20, 18, 16, 13, 10, 8, 11, 14, 17, 20, 23, 26, 28, 26, 23, 20, 18, 16, 13, 10],
        'close': [11, 14, 16, 14, 17, 19, 21, 20, 23, 26, 24, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26, 23, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26, 23, 21, 19, 16, 13, 11, 14, 17, 20, 23, 26, 29, 31, 29, 26, 23, 21, 19, 16, 13],
        'volume': [100, 120, 110, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300, 310, 320, 330, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440, 450, 460, 470, 480, 490, 500, 510, 520, 530, 540, 550, 560, 570, 580, 590, 600, 610, 620, 630, 640, 650, 660, 670, 680, 690]
    }
    df = pd.DataFrame(data)

    stoch_rsi_indicator = StochasticRSI()

    # Test with default parameters
    df_stoch_rsi_default = stoch_rsi_indicator.calculate(df.copy())
    print("\nDataFrame with default Stochastic RSI (14, 14, 3, 3, source='close'):")
    print(df_stoch_rsi_default[[f"StochRSI_K_14_14_3_3", f"StochRSI_D_14_14_3_3"]].tail())

    # Test with custom parameters
    custom_rsi_len = 7
    custom_stoch_len = 7
    custom_k = 2
    custom_d = 2
    df_stoch_rsi_custom = stoch_rsi_indicator.calculate(df.copy(), rsi_length=custom_rsi_len, stoch_length=custom_stoch_len, k_period=custom_k, d_period=custom_d, source="close")
    print(f"\nDataFrame with custom Stochastic RSI ({custom_rsi_len}, {custom_stoch_len}, {custom_k}, {custom_d}, source='close'):")
    print(df_stoch_rsi_custom[[f"StochRSI_K_{custom_rsi_len}_{custom_stoch_len}_{custom_k}_{custom_d}", f"StochRSI_D_{custom_rsi_len}_{custom_stoch_len}_{custom_k}_{custom_d}"]].tail())

    # Test required history
    print(f"\nRequired history for default Stochastic RSI: {stoch_rsi_indicator.required_history()}")
    print(f"Required history for custom Stochastic RSI ({custom_rsi_len}, {custom_stoch_len}, {custom_k}, {custom_d}): {stoch_rsi_indicator.required_history(rsi_length=custom_rsi_len, stoch_length=custom_stoch_len, k_period=custom_k, d_period=custom_d)}")

    # Test with insufficient data
    print("\nTesting with insufficient data:")
    df_small = df.head(5)
    df_stoch_rsi_small = stoch_rsi_indicator.calculate(df_small.copy())
    print(df_stoch_rsi_small[[f"StochRSI_K_14_14_3_3", f"StochRSI_D_14_14_3_3"]])

    # Test with missing source column
    print("\nTesting with missing source column:")
    df_no_close = df.drop(columns=['close'])
    try:
        stoch_rsi_indicator.calculate(df_no_close.copy(), source="close")
    except ValueError as e:
        print(f"Caught expected error: {e}")
