from typing import Any, List, Dict, Literal, Optional
import pandas as pd
import pandas_ta as ta
import logging

from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator

logger = logging.getLogger(__name__)

class SMI(BaseIndicator):
    NAME = "SMI"
    DISPLAY_NAME = "Stochastic Momentum Index"
    PANE_TYPE = "pane" # Typically displayed in a separate pane
    SCALE_TYPE = "percentage" # Typically ranges from -100 to 100 or 0 to 100

    PARAMETERS = [
        BotParameter(
            name="k_length",
            parameter_type="int",
            display_name="%K Length",
            description="The number of periods for the %K calculation.",
            default_value=10,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="d_length",
            parameter_type="int",
            display_name="%D Length",
            description="The number of periods for the %D (signal line) calculation.",
            default_value=3,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="smoothing_length",
            parameter_type="int",
            display_name="Smoothing Length",
            description="The number of periods for the initial smoothing of the SMI.",
            default_value=3,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="source",
            parameter_type="enum",
            display_name="Source",
            description="The data column to use for SMI calculation (e.g., 'close', 'open', 'high', 'low').",
            default_value="close",
            options=["open", "high", "low", "close"]
        ),
    ]

    def calculate(self, df: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the Stochastic Momentum Index (SMI) and adds it to the DataFrame.
        The column names will be SMI_k_length_d_length_smoothing_length and SMI_d_length_smoothing_length.
        """
        k_length = params.get("k_length", self.PARAMETERS[0].default_value)
        d_length = params.get("d_length", self.PARAMETERS[1].default_value)
        smoothing_length = params.get("smoothing_length", self.PARAMETERS[2].default_value)
        source = params.get("source", self.PARAMETERS[3].default_value)

        if source not in df.columns:
            logger.error(f"Source column '{source}' not found in DataFrame for SMI calculation.")
            df[f"SMI_{k_length}_{d_length}_{smoothing_length}"] = pd.NA
            df[f"SMI_Signal_{k_length}_{d_length}_{smoothing_length}"] = pd.NA
            return df
        
        # Ensure the source column is numeric
        df[source] = pd.to_numeric(df[source], errors='coerce')

        # pandas_ta handles NaN values internally, but we should ensure enough data
        required_bars = max(k_length, d_length, smoothing_length) + 1 # A bit more conservative
        if len(df) < required_bars:
            logger.warning(f"Not enough data ({len(df)} bars) for SMI calculation. Needs at least {required_bars} bars.")
            df[f"SMI_{k_length}_{d_length}_{smoothing_length}"] = pd.NA
            df[f"SMI_Signal_{k_length}_{d_length}_{smoothing_length}"] = pd.NA
            return df

        try:
            # pandas_ta's `smi` function calculates both SMI and its signal line
            # It uses 'close', 'high', 'low' by default. We need to ensure 'source' is handled.
            # pandas_ta.smi uses 'close' for the main calculation, and 'high'/'low' for range.
            # If source is not 'close', we might need to adjust.
            # For simplicity, let's assume 'close' is the primary source for SMI calculation
            # and high/low are always available for range.
            # If the user selects 'open', 'high', or 'low' as source, it's usually for the main price series.
            # SMI inherently needs high/low for its range calculation.
            # Let's use the 'close' for the main SMI calculation, and high/low for the range.
            # If the 'source' parameter is intended to replace 'close' in the SMI formula,
            # then pandas_ta.smi might not directly support it without custom implementation.
            # For now, I'll use the default pandas_ta behavior which uses 'close' for the main SMI line
            # and high/low for the range. The 'source' parameter will be used for the main price series
            # if it's not 'close', but SMI calculation itself needs high/low.
            # A more robust solution would be to pass the source to the SMI calculation if pandas_ta supports it,
            # or implement SMI manually if it doesn't.
            # For now, I'll proceed with pandas_ta's default SMI calculation which uses close, high, low.
            # The 'source' parameter will be used for the main price series if it's not 'close',
            # but SMI calculation itself needs high/low.
            # Let's assume the 'source' parameter is for the main price series, and SMI needs high/low.
            # If source is 'close', it's straightforward. If not, it's a bit ambiguous with pandas_ta.smi.
            # I will use the 'close' column for the SMI calculation, as it's the most common.
            # If the user wants to use 'open', 'high', or 'low' as the primary input for SMI,
            # a custom implementation or a different pandas_ta function might be needed.

            # pandas_ta.smi requires high, low, close.
            # The 'source' parameter in our BotParameter is usually for the main price series.
            # For SMI, the calculation inherently uses high, low, and close.
            # I will use df['close'] for the main SMI calculation, and df['high'], df['low'] for the range.
            # The 'source' parameter will be ignored for the actual SMI calculation,
            # but it's kept in PARAMETERS for consistency with other indicators.
            # A note in the description of the 'source' parameter might be useful if this is a strict requirement.

            # Let's use the pandas_ta.smi function. It returns a DataFrame with SMI and SMI_Signal.
            # The default column names are SMI_k_d_s and SMIs_k_d_s.
            smi_df = ta.smi(
                close=df['close'],
                high=df['high'],
                low=df['low'],
                k=k_length,
                d=d_length,
                append=True
            )
            
            # Rename columns to match our convention
            smi_col_name = f"SMI_{k_length}_{d_length}_{smoothing_length}"
            signal_col_name = f"SMI_Signal_{k_length}_{d_length}_{smoothing_length}"

            # pandas_ta.smi returns columns like SMI_10_3_3 and SMIs_10_3_3
            # We need to map these to our desired names.
            # The 'smoothing_length' parameter in our definition is for the initial smoothing,
            # which pandas_ta.smi handles internally with its 's' parameter.
            # The 'd_length' in pandas_ta.smi is for the signal line.
            # Let's align our parameters with pandas_ta's 'k', 'd', 's'
            # Our k_length -> pandas_ta k
            # Our smoothing_length -> pandas_ta s
            # Our d_length -> pandas_ta d (for signal line)

            # Re-evaluating parameters for pandas_ta.smi:
            # ta.smi(close, high, low, k=10, d=3, s=3, append=False)
            # k: %K length (our k_length)
            # d: %D length (our d_length)
            # s: smoothing length (our smoothing_length)

            smi_df = ta.smi(
                close=df[source], # Use the specified source for the main calculation
                high=df['high'],
                low=df['low'],
                k=k_length,
                d=d_length,
                s=smoothing_length, # Use our smoothing_length for 's'
                append=True
            )
            
            # The columns returned by pandas_ta.smi are typically like 'SMI_K_D_S' and 'SMIs_K_D_S'
            # We need to find the exact names generated by pandas_ta
            # A safer way is to check the columns of smi_df
            smi_main_col = [col for col in smi_df.columns if col.startswith('SMI_') and not col.startswith('SMIs_')][0]
            smi_signal_col = [col for col in smi_df.columns if col.startswith('SMIs_')][0]

            df[f"SMI_{k_length}_{d_length}_{smoothing_length}"] = smi_df[smi_main_col]
            df[f"SMI_Signal_{k_length}_{d_length}_{smoothing_length}"] = smi_df[smi_signal_col]

        except Exception as e:
            logger.error(f"Error calculating SMI({k_length}, {d_length}, {smoothing_length}) from source '{source}': {e}", exc_info=True)
            df[f"SMI_{k_length}_{d_length}_{smoothing_length}"] = pd.NA
            df[f"SMI_Signal_{k_length}_{d_length}_{smoothing_length}"] = pd.NA
        return df

    def required_history(self, k_length: int, d_length: int, smoothing_length: int, source: str = "close") -> int:
        """
        Returns the minimum number of historical bars required for SMI calculation.
        SMI typically needs max(k_length, d_length, smoothing_length) bars.
        """
        return max(k_length, d_length, smoothing_length) + 1 # Add 1 for buffer

# Register the indicator
register_indicator(SMI.NAME, SMI)

if __name__ == "__main__":
    # Example usage for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Create a sample DataFrame
    data = {
        'open': [10, 12, 15, 13, 16, 18, 20, 19, 22, 25, 23, 26, 28, 27, 30, 32, 35, 33, 36, 38, 40, 39, 42, 45, 43],
        'high': [13, 16, 17, 15, 19, 20, 22, 21, 24, 27, 25, 29, 30, 29, 32, 34, 37, 35, 38, 40, 42, 41, 44, 47, 45],
        'low': [9, 11, 13, 12, 14, 16, 18, 17, 20, 23, 21, 24, 26, 25, 28, 30, 33, 31, 34, 36, 38, 37, 40, 43, 41],
        'close': [12, 15, 14, 16, 18, 19, 21, 20, 23, 24, 25, 27, 29, 28, 31, 33, 36, 34, 37, 39, 41, 40, 43, 44, 42],
    }
    df = pd.DataFrame(data, index=pd.to_datetime(pd.date_range(start='2023-01-01', periods=len(data['close']), freq='D')))

    smi_indicator = SMI()

    # Calculate SMI with default parameters
    df_smi_default = smi_indicator.calculate(df.copy())
    print("\nDataFrame with SMI (default parameters):")
    print(df_smi_default[[f"SMI_10_3_3", f"SMI_Signal_10_3_3", "close"]].tail())

    # Calculate SMI with custom parameters
    custom_k = 14
    custom_d = 5
    custom_s = 5
    df_smi_custom = smi_indicator.calculate(df.copy(), k_length=custom_k, d_length=custom_d, smoothing_length=custom_s, source="close")
    print(f"\nDataFrame with custom SMI (k={custom_k}, d={custom_d}, s={custom_s}, source='close'):")
    print(df_smi_custom[[f"SMI_{custom_k}_{custom_d}_{custom_s}", f"SMI_Signal_{custom_k}_{custom_d}_{custom_s}", "close"]].tail())

    # Test required history
    print(f"\nRequired history for default SMI: {smi_indicator.required_history(k_length=10, d_length=3, smoothing_length=3)}")
    print(f"Required history for custom SMI (k={custom_k}, d={custom_d}, s={custom_s}): {smi_indicator.required_history(k_length=custom_k, d_length=custom_d, smoothing_length=custom_s)}")

    # Test with insufficient data
    df_small = df.iloc[:5]
    df_smi_small = smi_indicator.calculate(df_small.copy())
    print("\nDataFrame with SMI (insufficient data):")
    print(df_smi_small[[f"SMI_10_3_3", f"SMI_Signal_10_3_3", "close"]].tail())

    # Test with missing source column
    print("\nTesting with missing source column:")
    df_no_close = df.drop(columns=['close'])
    try:
        smi_indicator.calculate(df_no_close.copy(), source="close")
    except Exception as e:
        print(f"Caught expected error: {e}")
