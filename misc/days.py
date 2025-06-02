# --- Code from Step 2: Load Data ---
import pandas as pd

# Configuration from Step 2 (Update this path!)
csv_file_path = 'XAU_USD_M1_2019-01-01_to_2025-04-30.csv'
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


import numpy as np # Need numpy for np.select

print("\n--- Analyzing Daily Trend (Asia Close vs. Previous NY Close) Distribution by Weekday ---")

try:
    # Get New York session Close price and its Date
    ny_closes_daily = sessions_df.loc[(slice(None), 'NewYork'), ['Close']].reset_index()
    ny_closes_daily = ny_closes_daily[['Date', 'Close']].rename(columns={'Close': 'Previous_NY_Close'})

    # Shift the Date forward by one day to align NY Day N with Asia Day N+1 for merging
    # The 'Date' column in the merged dataframe will be the date of the Asia session (Day N+1)
    ny_closes_daily['Date'] = ny_closes_daily['Date'] + pd.Timedelta(days=1)


    # Get Asia session Close price and its Date
    asia_closes_daily = sessions_df.loc[(slice(None), 'Asia'), ['Close']].reset_index()
    asia_closes_daily = asia_closes_daily[['Date', 'Close']].rename(columns={'Close': 'Asia_Close'})


    # Merge the shifted NY closes with Asia closes on the Date
    daily_trend_data = pd.merge(
        asia_closes_daily,
        ny_closes_daily,
        on='Date',
        how='inner' # Only include days where both a preceding NY and the current Asia session exist
    )

    # --- FIX: Ensure the 'Date' column is a proper datetime type AFTER merging ---
    # The .dt accessor requires the column to be datetime64[ns] or similar.
    # Convert the 'Date' column to datetime objects.
    daily_trend_data['Date'] = pd.to_datetime(daily_trend_data['Date'])


    # --- Determine the Daily Trend Outcome ---
    # Define conditions and choices for the outcome compared to Previous_NY_Close
    conditions = [
        daily_trend_data['Asia_Close'] > daily_trend_data['Previous_NY_Close'],
        daily_trend_data['Asia_Close'] < daily_trend_data['Previous_NY_Close'],
        daily_trend_data['Asia_Close'] == daily_trend_data['Previous_NY_Close']
    ]
    choices = ['Up', 'Down', 'Flat'] # 'Up' means Asia Close > Previous NY Close

    # Use numpy.select to create the 'Outcome' column
    daily_trend_data['Outcome'] = np.select(conditions, choices, default='Unknown') # Default should not happen with these conditions

    # --- Get the Weekday ---
    # Now .dt.day_name() should work because 'Date' is datetime64
    daily_trend_data['Weekday'] = daily_trend_data['Date'].dt.day_name()

    # --- Analyze Distribution by Weekday ---

    # Group the data by Weekday and count the occurrences of each 'Outcome'
    weekday_counts = daily_trend_data.groupby('Weekday')['Outcome'].value_counts().unstack(fill_value=0)

    # Ensure all weekdays are present in a consistent trading order (Mon-Fri)
    # Reindex will add rows for missing weekdays if any and fill with 0
    weekdays_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    # Use reindex with fill_value=0 in case a day has zero instances of any outcome
    weekday_counts = weekday_counts.reindex(weekdays_order, fill_value=0)


    # Calculate total instances for each weekday
    weekday_counts['Total'] = weekday_counts.sum(axis=1)

    # Calculate the percentage of 'Up' outcomes (Asia Close > Previous NY Close) for each weekday
    # Use .get('Up', 0) to handle cases where a weekday might have no 'Up' outcomes at all
    # Avoid division by zero if a weekday has 0 total instances (e.g., if data was only Mon-Weds for a brief period)
    weekday_counts['Percentage_Up'] = (weekday_counts.get('Up', 0) / weekday_counts['Total']) * 100
    # Handle potential inf/nan from division by zero resulting in NaN or Inf
    weekday_counts['Percentage_Up'] = weekday_counts['Percentage_Up'].replace([np.inf, -np.inf], np.nan).fillna(0)
    weekday_counts['Percentage_Up'] = weekday_counts['Percentage_Up'].round(2) # Round to 2 decimal places


    # Print the results
    # Print just the date part of the min/max date for cleaner output
    print(f"Analysis Period: {daily_trend_data['Date'].min().date()} to {daily_trend_data['Date'].max().date()}")
    print(f"Total comparable days across all weekdays: {len(daily_trend_data)}")
    print("\nDistribution of Daily Trend (Asia Close > Previous NY Close) by Weekday:")
    # Print the counts for Up, Down, Flat, the total for the weekday, and the calculated percentage of Up days
    print(weekday_counts[['Total', 'Up', 'Down', 'Flat', 'Percentage_Up']])


except Exception as e:
    print(f"An error occurred during the analysis: {e}")

print("--- Analysis Complete ---")