# --- Code from Step 2: Load Data ---
import pandas as pd

# Configuration from Step 2 (Update this path!)
csv_file_path = 'USD_JPY_M1_2019-01-01_to_2025-05-08.csv'
time_column = 'time'
ohlcv_columns = ['open', 'high', 'low', 'close', 'volume']

print(f"Loading data from: {csv_file_path}")

try:
    df = pd.read_csv(
        csv_file_path,
        parse_dates=[time_column],
        index_col=time_column
    )
    if not all(col in df.columns for col in ohlcv_columns):
         print("Error: Not all expected OHLCV columns found.")
         # You might want to exit or handle this case
    else:
        df = df[ohlcv_columns]
        print("Data loaded successfully.")
        # print(df.head()) # Can print head here to confirm if you like
        # print(df.info()) # Can print info here

except FileNotFoundError:
    print(f"Error: The file was not found at {csv_file_path}")
    # Handle error, perhaps exit the script
except Exception as e:
    print(f"An error occurred during file loading or processing: {e}")
    # Handle error

# --- Check if df was successfully loaded before proceeding ---
if 'df' in locals() and isinstance(df, pd.DataFrame) and not df.empty:
    print("\nProceeding with session aggregation...")

    # --- Code from Step 3: Define Trading Sessions and Aggregate ---

    # Define Session Times in UTC (Hour, Minute)
    session_time_ranges = {
        'Asia': (pd.Timedelta(hours=0), pd.Timedelta(hours=9, minutes=0)),
        'London': (pd.Timedelta(hours=8), pd.Timedelta(hours=17, minutes=0)),
        'NewYork': (pd.Timedelta(hours=13), pd.Timedelta(hours=22, minutes=0))
    }

    session_list = []
    all_dates_utc = df.index.normalize().unique()

    print(f"Aggregating data for {len(all_dates_utc)} unique UTC dates...")

    for day in all_dates_utc:
        day_window_start = day
        day_window_end = day + pd.Timedelta(days=1)

        data_for_day_window = df.loc[day_window_start : day_window_end]

        if data_for_day_window.empty:
            continue

        for session_name, (start_delta, end_delta) in session_time_ranges.items():
            session_start_ts = day + start_delta
            session_end_ts = day + end_delta

            # Filter data for the specific session range
            # Use .loc and include end=True implicitly for Timestamps
            session_data = data_for_day_window.loc[session_start_ts : session_end_ts].copy()

            if session_data.empty:
                continue

            # Aggregate session data
            session_open = session_data['open'].iloc[0]
            session_high = session_data['high'].max()
            session_low = session_data['low'].min()
            session_close = session_data['close'].iloc[-1]
            session_volume = session_data['volume'].sum()
            session_range = session_high - session_low

            session_direction = 0
            if session_close > session_open:
                session_direction = 1
            elif session_close < session_open:
                session_direction = -1

            session_list.append({
                'Date': day.date(),
                'Session': session_name,
                'OpenTime': session_data.index[0],
                'CloseTime': session_data.index[-1],
                'Open': session_open,
                'High': session_high,
                'Low': session_low,
                'Close': session_close,
                'Volume': session_volume,
                'Range': session_range,
                'Direction': session_direction
            })

    sessions_df = pd.DataFrame(session_list)
    sessions_df = sessions_df.set_index(['Date', 'Session']).sort_index()


    print("\nSession aggregation complete.")
    print("\nFirst 5 rows of aggregated session data:")
    print(sessions_df.head())

    print("\nAggregated session data info:")
    sessions_df.info()

    print(f"\nTotal number of sessions aggregated: {len(sessions_df)}")

else:
    print("\nDataFrame 'df' was not loaded successfully. Cannot proceed with aggregation.")


# Assuming df (original 1-min data) and sessions_df (aggregated session data)
# from previous steps are already loaded and ready

print("\n--- Analyzing Timing of London Session Highs and Lows ---")

try:
    # Filter for only London sessions from the aggregated data
    london_sessions_agg = sessions_df.loc[(slice(None), 'London'), :].reset_index()

    timing_data_list = []
    skipped_sessions_timing = 0

    total_london_sessions = len(london_sessions_agg)
    print(f"Analyzing timing for {total_london_sessions} London sessions...")

    # Iterate through each London session instance
    for index, session_row in london_sessions_agg.iterrows():
        session_date = session_row['Date']
        session_opentime = session_row['OpenTime']
        session_closetime = session_row['CloseTime']
        session_high_price = session_row['High'] # Get the aggregated High to find its exact time
        session_low_price = session_row['Low']   # Get the aggregated Low to find its exact time


        # Basic validation for session time range
        if session_closetime <= session_opentime:
             # print(f"Skipping invalid London session starting {session_opentime} (CloseTime <= OpenTime).")
             skipped_sessions_timing += 1
             continue

        # Get the data for this specific London session from the original 1-min DataFrame (df)
        session_1min_data = df.loc[session_opentime : session_closetime].copy()


        if session_1min_data.empty:
            # print(f"Skipping London session starting {session_opentime} due to empty 1-min data range.")
            skipped_sessions_timing += 1
            continue # Skip if no 1-minute data found for the session range

        high_time = None
        low_time = None

        try:
            # Find the timestamp(s) where the session's High price occurred
            high_bars = session_1min_data[session_1min_data['high'] == session_high_price]
            if not high_bars.empty:
                # Take the time of the *first* high occurrence
                high_time = high_bars.index[0]

            # Find the timestamp(s) where the session's Low price occurred
            low_bars = session_1min_data[session_1min_data['low'] == session_low_price]
            if not low_bars.empty:
                 # Take the time of the *first* low occurrence
                 low_time = low_bars.index[0]

            # If both high_time and low_time were successfully found for this session
            if high_time is not None and low_time is not None:
                 timing_data_list.append({
                     'Date': session_date, # Include date for potential future use
                     'OpenTime': session_opentime,
                     'HighTime': high_time,
                     'LowTime': low_time
                 })
            else:
                 # If we found data but couldn't find high/low time (unlikely but robust)
                 # print(f"Warning: Could not find both High/Low timestamps for session starting {session_opentime}. Skipping.")
                 skipped_sessions_timing += 1 # Count as skipped for analysis


        except Exception as e:
            # Catch any other potential errors during slicing or finding index
            # print(f"An error occurred processing session starting {session_opentime} for timing: {e}. Skipping.")
            skipped_sessions_timing += 1


    # --- Proceed with Analysis if valid timing data was extracted ---

    if not timing_data_list:
        print("\nNo valid timing data was extracted for analysis.")
    else:
        # Convert the list of timing data into a DataFrame
        timing_df = pd.DataFrame(timing_data_list)
        # Optional: Set date as index if needed later, but not required for current calculations
        # timing_df = timing_df.set_index('Date')


        # --- Analyze the Distribution of High/Low Times by UTC Hour ---

        # Analyze frequency by the absolute UTC hour of the day
        high_hour_counts = timing_df['HighTime'].dt.hour.value_counts().sort_index()
        low_hour_counts = timing_df['LowTime'].dt.hour.value_counts().sort_index()

        print(f"\nSuccessfully extracted timing for {len(timing_df)} London sessions Highs and Lows.")
        if skipped_sessions_timing > 0:
             print(f"Skipped {skipped_sessions_timing} London sessions due to data/processing issues for timing analysis.")


        print("\nFrequency Distribution of London Session Highs by UTC Hour:")
        # Print counts and percentages
        print(high_hour_counts)
        print((high_hour_counts / high_hour_counts.sum() * 100).round(2))


        print("\nFrequency Distribution of London Session Lows by UTC Hour:")
        # Print counts and percentages
        print(low_hour_counts)
        print((low_hour_counts / low_hour_counts.sum() * 100).round(2))


        # --- Analyze by Time Since Open (e.g., hourly bins relative to open) ---

        # Calculate duration from session open for each High/Low time in minutes
        # This is done correctly now by subtracting the OpenTime column from the HighTime/LowTime columns in the same DataFrame
        timing_df['High_Duration_Minutes'] = (timing_df['HighTime'] - timing_df['OpenTime']).dt.total_seconds() / 60
        timing_df['Low_Duration_Minutes'] = (timing_df['LowTime'] - timing_df['OpenTime']).dt.total_seconds() / 60

        # Define bins in minutes (e.g., 0-59, 60-119, etc.) for 9-hour session (540 minutes)
        bins = range(0, 541, 60) # Bins from 0 up to 540, in steps of 60 minutes
        bin_labels = [f'{i}-{i+59} min' for i in bins[:-1]] # Labels like '0-59 min', '60-119 min', etc.


        high_duration_bins = pd.cut(timing_df['High_Duration_Minutes'], bins=bins, labels=bin_labels, right=False, include_lowest=True) # right=False means [0, 60)
        low_duration_bins = pd.cut(timing_df['Low_Duration_Minutes'], bins=bins, labels=bin_labels, right=False, include_lowest=True)


        high_duration_counts = high_duration_bins.value_counts().sort_index()
        low_duration_counts = low_duration_bins.value_counts().sort_index()


        print("\nFrequency Distribution of London Session Highs by Minutes Since Open:")
        print(high_duration_counts)
        print((high_duration_counts / high_duration_counts.sum() * 100).round(2))


        print("\nFrequency Distribution of London Session Lows by Minutes Since Open:")
        print(low_duration_counts)
        print((low_duration_counts / low_duration_counts.sum() * 100).round(2))


except Exception as e:
    print(f"An error occurred during the overall timing analysis: {e}")

print("--- Analysis Complete ---")