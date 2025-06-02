import pandas as pd
from datetime import datetime, timezone, timedelta
import oandapyV20
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# It's better to fetch API access token from settings or environment variables
# For now, assuming it might be set in settings.OANDA_ACCESS_TOKEN
# If not, this will need adjustment.
try:
    OANDA_ACCESS_TOKEN = settings.OANDA_ACCESS_TOKEN
    OANDA_ENVIRONMENT = getattr(settings, 'OANDA_ENVIRONMENT', 'practice') # Default to practice
except AttributeError:
    logger.error("OANDA_ACCESS_TOKEN not found in Django settings. Please configure it.")
    OANDA_ACCESS_TOKEN = "YOUR_DEFAULT_TOKEN_OR_NONE" # Fallback or raise error
    OANDA_ENVIRONMENT = "practice"

if OANDA_ACCESS_TOKEN == "YOUR_DEFAULT_TOKEN_OR_NONE":
    logger.warning("Using a placeholder OANDA_ACCESS_TOKEN for data_fetcher.py. This will likely fail.")

api = API(access_token=OANDA_ACCESS_TOKEN, environment=OANDA_ENVIRONMENT)

def get_historical_m1_data(instrument_symbol: str, start_time: datetime, end_time: datetime) -> pd.DataFrame:
    """
    Fetches M1 historical data for a given instrument from start_time to end_time.
    OANDA uses '_' for pairs like EUR_USD.
    """
    all_dfs = []
    current_dt = start_time
    # OANDA max count is 5000 candles per request for InstrumentsCandles
    batch_size = 5000 
    time_delta_per_batch = timedelta(minutes=batch_size) # Max time covered by one batch of M1 data

    logger.info(f"Fetching M1 data for {instrument_symbol} from {start_time} to {end_time}")

    while current_dt < end_time:
        # Determine 'to' time for the current batch to not exceed end_time
        # and also not exceed OANDA's implicit limit based on count
        # OANDA's 'to' is exclusive, 'from' is inclusive for InstrumentsCandles
        # We control the window primarily by 'from' and 'count'.
        # The 'to' parameter can be used to cap the request if needed, but 'count' is more direct.
        
        params = {
            "from": current_dt.isoformat(),
            "granularity": "M1",
            "count": batch_size,
            # "to": (current_dt + time_delta_per_batch).isoformat() # Optional: can cap with 'to'
        }
        
        # If the remaining window is smaller than a full batch, adjust count
        remaining_minutes = (end_time - current_dt).total_seconds() / 60
        if remaining_minutes < batch_size:
            params["count"] = int(max(1, remaining_minutes)) # Ensure count is at least 1

        if params["count"] == 0 : # No more data to fetch
             break


        logger.debug(f"Requesting OANDA: {instrument_symbol}, params: {params}")
        r = InstrumentsCandles(instrument=instrument_symbol, params=params)
        
        try:
            resp = api.request(r)
            candles = resp.get("candles", [])
            if not candles:
                logger.info(f"No more candles returned for {instrument_symbol} from {current_dt}. Ending fetch.")
                break

            df = pd.DataFrame([{
                "time": pd.to_datetime(c["time"]),
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "volume": int(c["volume"])
            } for c in candles if c.get('mid')]).set_index("time") # Ensure 'mid' exists

            if df.empty:
                logger.info(f"Empty DataFrame after processing candles for {instrument_symbol} from {current_dt}.")
                # This might happen if all candles lacked 'mid' price data.
                # To avoid infinite loop if current_dt doesn't advance:
                current_dt += time_delta_per_batch # Still advance time to avoid getting stuck
                if current_dt > end_time and not all_dfs: # If we overshoot and got nothing, break
                    break
                continue


            logger.debug(f"Fetched {len(df)} bars for {instrument_symbol} from {df.index.min()} to {df.index.max()}")
            all_dfs.append(df)
            
            last_ts_in_batch = df.index.max()
            if last_ts_in_batch >= end_time - timedelta(minutes=1): # Reached or passed the end_time
                break
            
            current_dt = last_ts_in_batch + timedelta(minutes=1) # Move to the next minute after the last fetched candle

        except oandapyV20.exceptions.V20Error as e:
            logger.error(f"OANDA API error for {instrument_symbol}: {e}. Params: {params}")
            # Depending on error, might retry or break. For now, break.
            # e.g., if e.code == 400 and "maximum pips" or "future" error, adjust params or stop.
            break 
        except Exception as e:
            logger.error(f"Generic error fetching data for {instrument_symbol}: {e}. Params: {params}")
            break
            
    if not all_dfs:
        logger.warning(f"No data fetched for {instrument_symbol} in range {start_time} to {end_time}.")
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume']).set_index(pd.DatetimeIndex([]))

    full_df = pd.concat(all_dfs).sort_index()
    # Ensure data is within the requested range (inclusive start, exclusive end for OANDA consistency)
    # However, our function implies inclusive end, so filter accordingly.
    full_df = full_df.loc[start_time : end_time] 
    full_df = full_df[~full_df.index.duplicated(keep='first')] # Remove duplicates if any from overlaps
    logger.info(f"Completed fetching for {instrument_symbol}. Total bars: {len(full_df)}")
    return full_df

def get_latest_m1_data(instrument_symbol: str, last_timestamp: datetime) -> pd.DataFrame:
    """
    Fetches M1 data from last_timestamp up to the current time.
    """
    start_time = last_timestamp + timedelta(minutes=1) # Start from the minute after the last known data
    end_time = datetime.now(timezone.utc)
    
    if start_time >= end_time:
        logger.info(f"No new data to fetch for {instrument_symbol}. Last timestamp: {last_timestamp}, current time: {end_time}")
        return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume']).set_index(pd.DatetimeIndex([]))
        
    return get_historical_m1_data(instrument_symbol, start_time, end_time)

# Example usage (for testing this module directly):
if __name__ == '__main__':
    # Configure Django settings if running standalone for testing
    # This is a simplified setup. For proper Django context, use manage.py shell or a test runner.
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_platform.settings')
    import django
    django.setup()
    
    # Ensure OANDA_ACCESS_TOKEN is set in your project's settings.py for this test to run
    if not hasattr(settings, 'OANDA_ACCESS_TOKEN') or settings.OANDA_ACCESS_TOKEN == "YOUR_DEFAULT_TOKEN_OR_NONE":
        print("Please set OANDA_ACCESS_TOKEN in trading_platform/settings.py to run this example.")
    else:
        print(f"Using OANDA Token: {settings.OANDA_ACCESS_TOKEN[:5]}... Environment: {OANDA_ENVIRONMENT}")
        
        test_symbol = "EUR_USD"
        # Test fetching a small recent batch
        # test_start = datetime.now(timezone.utc) - timedelta(minutes=120)
        # test_end = datetime.now(timezone.utc) - timedelta(minutes=60)
        # print(f"\n--- Testing get_historical_m1_data for {test_symbol} from {test_start} to {test_end} ---")
        # df_hist = get_historical_m1_data(test_symbol, test_start, test_end)
        # print(f"Fetched {len(df_hist)} bars.")
        # if not df_hist.empty:
        #     print(df_hist.head())
        #     print(df_hist.tail())

        # Test fetching latest data (assuming some data exists)
        # last_known_time = datetime.now(timezone.utc) - timedelta(days=1) # Simulate last update was a day ago
        # print(f"\n--- Testing get_latest_m1_data for {test_symbol} since {last_known_time} ---")
        # df_latest = get_latest_m1_data(test_symbol, last_known_time)
        # print(f"Fetched {len(df_latest)} new bars.")
        # if not df_latest.empty:
        #     print(df_latest.head())
        #     print(df_latest.tail())

        # Test fetching a longer historical period
        long_test_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        long_test_end = datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc) # 3 hours of data
        print(f"\n--- Testing get_historical_m1_data for {test_symbol} from {long_test_start} to {long_test_end} ---")
        df_long_hist = get_historical_m1_data(test_symbol, long_test_start, long_test_end)
        print(f"Fetched {len(df_long_hist)} bars for long history.")
        if not df_long_hist.empty:
            print(f"Data from {df_long_hist.index.min()} to {df_long_hist.index.max()}")
            print(df_long_hist.head())
            print(df_long_hist.tail())
        else:
            print("No data returned for the long historical period.")
