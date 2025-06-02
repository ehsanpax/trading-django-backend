import pandas as pd
from django.conf import settings
import logging
import pyarrow.parquet as pq
from pathlib import Path

logger = logging.getLogger(__name__)

def load_m1_data_from_parquet(instrument_symbol: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    """
    Loads M1 data from local Parquet files for a given instrument and date range.
    Data is expected to be stored in data/{symbol}/M1.parquet.
    Applies date filters directly during load if possible.
    """
    data_root = Path(settings.DATA_ROOT)
    parquet_file_path = data_root / instrument_symbol / "M1.parquet"

    logger.info(f"Loading M1 data for {instrument_symbol} from {parquet_file_path}, range: {start_date} to {end_date}")

    if not parquet_file_path.exists():
        logger.warning(f"Parquet file not found: {parquet_file_path}")
        return pd.DataFrame()

    try:
        # PyArrow filtering:
        # The filter expression should be a list of tuples.
        # Each tuple is (column_name, operator, value).
        # For time range, we need two conditions: (time >= start_date) AND (time <= end_date)
        # Ensure start_date and end_date are timezone-aware if the Parquet data is.
        # Assuming Parquet 'time' column is already a timestamp.
        
        # Convert start_date and end_date to pd.Timestamp if they are not already (e.g. datetime.date)
        start_ts = pd.Timestamp(start_date, tz='UTC' if start_date.tzinfo is None else None)
        end_ts = pd.Timestamp(end_date, tz='UTC' if end_date.tzinfo is None else None)
        
        # Adjust end_ts to be inclusive for the entire day if it's just a date
        if end_ts.hour == 0 and end_ts.minute == 0 and end_ts.second == 0:
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)


        filters = [
            ('time', '>=', start_ts),
            ('time', '<=', end_ts) # Inclusive end date
        ]
        
        logger.debug(f"Applying filters to Parquet read: {filters}")
        table = pq.read_table(parquet_file_path, filters=filters)
        df = table.to_pandas()
        
        if df.empty:
            logger.info(f"No data found for {instrument_symbol} in range {start_date} to {end_date} after filtering.")
            return df

        # Ensure index is DatetimeIndex and sorted
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'time' in df.columns:
                df = df.set_index('time')
            else: # If 'time' was the index but not recognized as DatetimeIndex
                 df.index = pd.to_datetime(df.index)

        df = df.sort_index()
        
        # Final explicit filter in pandas just in case Parquet filter wasn't precise enough or for other reasons
        df = df.loc[start_ts : end_ts]

        logger.info(f"Successfully loaded {len(df)} M1 bars for {instrument_symbol} from Parquet.")
        return df

    except Exception as e:
        logger.error(f"Error loading data from Parquet for {instrument_symbol}: {e}")
        return pd.DataFrame()


def resample_data(df_m1: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
    """
    Resamples M1 Pandas DataFrame to target timeframe (e.g., "M5", "M15", "H1").
    """
    if df_m1.empty:
        logger.warning("Input DataFrame for resampling is empty.")
        return pd.DataFrame()

    if not isinstance(df_m1.index, pd.DatetimeIndex):
        logger.error("DataFrame index must be a DatetimeIndex for resampling.")
        return pd.DataFrame()
        
    # Ensure standard OHLCV column names if they are different
    # For now, assumes 'open', 'high', 'low', 'close', 'volume'

    logger.info(f"Resampling M1 data to {target_timeframe}. Original rows: {len(df_m1)}")
    
    resampling_rules = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }

    # Map common timeframe strings to pandas offset aliases
    timeframe_mapping = {
        "M1": "1T", "M5": "5T", "M15": "15T", "M30": "30T",
        "H1": "1H", "H4": "4H",
        "D1": "1D", "W1": "1W", "MN1": "1M" # MN1 for 1 Month start
    }
    
    pandas_freq = timeframe_mapping.get(target_timeframe.upper(), target_timeframe)
    logger.info(f"Using pandas frequency string: {pandas_freq} for target_timeframe: {target_timeframe}")

    try:
        # The `label` and `closed` parameters might be important depending on exact requirements.
        # Default 'label' is 'left', 'closed' is 'left' for most frequencies.
        # For financial data, often 'right' label is preferred for period end.
        # e.g. an H1 bar ending at 10:00 should represent data from 09:00 to 10:00.
        # Let's assume standard pandas behavior is acceptable for now.
        # Using label='right' and closed='right' is common for OHLC financial data aggregation
        # to ensure the timestamp of the bar represents the end of the period.
        resampled_df = df_m1.resample(pandas_freq, label='right', closed='right').agg(resampling_rules)
        
        # Drop rows where all OHLCV values are NaN (often happens at the start/end of resampling periods if data is sparse)
        resampled_df.dropna(subset=['open', 'high', 'low', 'close'], how='all', inplace=True)
        
        logger.info(f"Resampling complete. New rows: {len(resampled_df)}")
        return resampled_df
        
    except Exception as e:
        logger.error(f"Error during resampling to {target_timeframe}: {e}")
        return pd.DataFrame()

def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates ATR, RSI, CMF, EMAs on a given DataFrame.
    Placeholder: This function will initially be very simple.
    It will be expanded later to include actual indicator calculations.
    """
    logger.info("calculate_all_indicators called (currently a placeholder).")
    # For now, just return the DataFrame as is.
    # Future implementation will add columns like 'atr', 'rsi', 'ema_20', etc.
    if 'volume' not in df.columns and not df.empty : # Ensure volume column exists for some indicators
        logger.warning("Volume column missing, adding it as zeros for indicator calculation placeholder.")
        df['volume'] = 0 
        
    return df

# Example usage (for testing this module directly):
if __name__ == '__main__':
    # Configure Django settings
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_platform.settings')
    import django
    django.setup()

    # Create a dummy Parquet file for testing
    data_root_path = Path(settings.DATA_ROOT)
    test_symbol_for_processor = "TEST_EURUSD"
    test_parquet_dir = data_root_path / test_symbol_for_processor
    test_parquet_dir.mkdir(parents=True, exist_ok=True)
    test_parquet_file = test_parquet_dir / "M1.parquet"

    # Create sample M1 data
    sample_start_time = pd.Timestamp("2023-01-01 00:00:00", tz='UTC')
    sample_end_time = pd.Timestamp("2023-01-01 03:00:00", tz='UTC')
    sample_index = pd.date_range(start=sample_start_time, end=sample_end_time, freq='1min')
    sample_data = {
        'open': [i + 1.0 for i in range(len(sample_index))],
        'high': [i + 1.5 for i in range(len(sample_index))],
        'low': [i + 0.5 for i in range(len(sample_index))],
        'close': [i + 1.2 for i in range(len(sample_index))],
        'volume': [100 + i * 10 for i in range(len(sample_index))]
    }
    sample_df_m1 = pd.DataFrame(sample_data, index=sample_index)
    sample_df_m1.index.name = 'time'
    
    if not sample_df_m1.empty:
        try:
            sample_df_m1.to_parquet(test_parquet_file)
            print(f"Created dummy Parquet file: {test_parquet_file}")

            # Test load_m1_data_from_parquet
            print(f"\n--- Testing load_m1_data_from_parquet ---")
            loaded_df = load_m1_data_from_parquet(
                test_symbol_for_processor,
                pd.Timestamp("2023-01-01 00:30:00", tz='UTC'),
                pd.Timestamp("2023-01-01 01:30:00", tz='UTC')
            )
            print(f"Loaded {len(loaded_df)} bars from Parquet.")
            if not loaded_df.empty:
                print(loaded_df.head())
                print(loaded_df.tail())

            # Test resample_data
            if not loaded_df.empty:
                print(f"\n--- Testing resample_data to M5 ---")
                resampled_m5_df = resample_data(loaded_df, "M5") # Using "M5"
                print(f"Resampled to M5, {len(resampled_m5_df)} bars.")
                if not resampled_m5_df.empty:
                    print(resampled_m5_df.head())
                
                print(f"\n--- Testing resample_data to H1 ---")
                resampled_h1_df = resample_data(loaded_df, "H1") # Using "H1"
                print(f"Resampled to H1, {len(resampled_h1_df)} bars.")
                if not resampled_h1_df.empty:
                    print(resampled_h1_df.head())

            # Test calculate_all_indicators (placeholder)
            if not loaded_df.empty:
                print(f"\n--- Testing calculate_all_indicators ---")
                indicators_df = calculate_all_indicators(loaded_df.copy()) # Use copy
                print(f"Indicators DataFrame (placeholder) has {len(indicators_df.columns)} columns.")
                if not indicators_df.empty:
                    print(indicators_df.head())
        except Exception as e:
            print(f"Error during data_processor self-test: {e}")
        finally:
            # Clean up dummy file
            if test_parquet_file.exists():
                # os.remove(test_parquet_file)
                # print(f"Removed dummy Parquet file: {test_parquet_file}")
                pass # Keep it for manual inspection if needed

    else:
        print("Sample M1 DataFrame is empty, skipping Parquet creation and tests.")
