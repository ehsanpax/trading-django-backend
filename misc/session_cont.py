# --- Code from Step 2: Load Data ---
import pandas as pd

# Configuration from Step 2 (Update this path!)
csv_file_path = 'AUD_USD_M1_2019-01-01_to_2025-05-08.csv'
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
        'Asia': (pd.Timedelta(hours=0), pd.Timedelta(hours=7, minutes=0)),
        'London': (pd.Timedelta(hours=7), pd.Timedelta(hours=14, minutes=0)),
        'NewYork': (pd.Timedelta(hours=14), pd.Timedelta(hours=23, minutes=0))
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


# Assuming sessions_df from Step 3 is already loaded and ready

print("\n--- Analyzing London to New York Trend Continuation ---")

try:
    # 1. Separate London and New York sessions
    london_sessions_cont = sessions_df.loc[(slice(None), 'Asia'), :].copy() # Use copy to avoid SettingWithCopyWarning
    newyork_sessions_cont = sessions_df.loc[(slice(None), 'London'), :].copy() # Use copy

    # Reset index to make 'Date' a regular column for merging
    london_sessions_cont = london_sessions_cont.reset_index()
    newyork_sessions_cont = newyork_sessions_cont.reset_index()

    # Rename Direction column to avoid conflict after merging
    london_sessions_cont = london_sessions_cont.rename(columns={'Direction': 'London_Direction'})
    newyork_sessions_cont = newyork_sessions_cont.rename(columns={'Direction': 'NewYork_Direction'})

    # Keep only necessary columns for merging and comparison
    london_sessions_cont = london_sessions_cont[['Date', 'London_Direction']]
    newyork_sessions_cont = newyork_sessions_cont[['Date', 'NewYork_Direction']]

    # 2. Align sessions by Date
    # Merge the two dataframes on the 'Date' column
    merged_sessions_ln = pd.merge(
        london_sessions_cont,
        newyork_sessions_cont,
        on='Date',
        how='inner' # Only include dates where both London and New York sessions exist
    )

    # 3. Compare Directions
    # Filter out instances where London session was flat (Direction == 0)
    directional_london_ny = merged_sessions_ln[merged_sessions_ln['London_Direction'] != 0].copy()

    # Check where New York Direction matches London Direction
    continuation_matches_ln = directional_london_ny[
        directional_london_ny['London_Direction'] == directional_london_ny['NewYork_Direction']
    ]

    # 4. Calculate Percentage
    total_comparable_days_ln = len(directional_london_ny)
    continuation_count_ln = len(continuation_matches_ln)

    if total_comparable_days_ln > 0:
        continuation_percentage_ln = (continuation_count_ln / total_comparable_days_ln) * 100
        print(f"Total days with directional London session & corresponding New York session: {total_comparable_days_ln}")
        print(f"Days where New York continued London's trend: {continuation_count_ln}")
        print(f"Percentage of times New York continued London's trend: {continuation_percentage_ln:.2f}%")
    else:
        print("Not enough comparable London and New York sessions found to perform the analysis.")

except Exception as e:
    print(f"An error occurred during the analysis: {e}")

print("--- Analysis Complete ---")