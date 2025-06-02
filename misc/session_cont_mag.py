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


# Assuming sessions_df from Step 3 is already loaded and ready

import pandas as pd

# Assuming sessions_df from Step 3 is already loaded and ready

import pandas as pd

# Assuming sessions_df from Step 3 is already loaded and ready

print("\n--- Analyzing New York to Asia Trend Continuation (Frequency) ---")

try:
    # Get New York session directions
    ny_dirs_n_a = sessions_df.loc[(slice(None), 'NewYork'), ['Direction']].reset_index()

    # Shift the Date forward by one day to align NY Day N with Asia Day N+1 for merging
    ny_dirs_n_a['Date'] = ny_dirs_n_a['Date'] + pd.Timedelta(days=1)

    # Rename Direction column to indicate it's from the previous day's NY session
    ny_dirs_n_a = ny_dirs_n_a.rename(columns={'Direction': 'Previous_NY_Direction'})

    # Get Asia session directions
    asia_dirs_n_a = sessions_df.loc[(slice(None), 'Asia'), ['Direction']].reset_index()
    asia_dirs_n_a = asia_dirs_n_a.rename(columns={'Direction': 'Asia_Direction'})


    # Merge the shifted NY directions with Asia directions on the Date
    # This joins Previous_NY_Direction (from Day N) with Asia_Direction (from Day N+1) using Day N+1's date
    merged_sessions_na = pd.merge(
        asia_dirs_n_a,
        ny_dirs_n_a,
        on='Date',
        how='inner' # Only include days where both a preceding NY and the current Asia session exist
    )

    # Filter out instances where Previous NY session was flat (no clear trend to continue)
    directional_ny_to_asia = merged_sessions_na[merged_sessions_na['Previous_NY_Direction'] != 0].copy()

    # Check where Asia Direction matches Previous NY Direction
    continuation_matches_na = directional_ny_to_asia[
        directional_ny_to_asia['Previous_NY_Direction'] == directional_ny_to_asia['Asia_Direction']
    ]

    # Calculate Frequency Percentage
    total_comparable_days_na = len(directional_ny_to_asia)
    continuation_count_na = len(continuation_matches_na)

    if total_comparable_days_na > 0:
        continuation_percentage_na = (continuation_count_na / total_comparable_days_na) * 100
        print(f"Analysis Period: {merged_sessions_na['Date'].min()} to {merged_sessions_na['Date'].max()}")
        print(f"Total days with directional Previous NY session & corresponding Asia session: {total_comparable_days_na}")
        print(f"Days where Asia continued Previous NY's trend: {continuation_count_na}")
        print(f"Percentage of times Asia continued Previous NY's trend: {continuation_percentage_na:.2f}%")
    else:
        print("Not enough comparable Previous NY and Asia sessions found to perform the frequency analysis.")

except Exception as e:
    print(f"An error occurred during the frequency analysis: {e}")

print("--- Frequency Analysis Complete ---")

# --- Now for Magnitude Analysis (Asia Range on Continuation/Reversal) ---

print("\n--- Analyzing Magnitude of Asia Continuation (Following Previous NY) ---")

try:
    # We need Previous NY Direction AND Asia Direction and Range for this analysis
    # Re-doing the merge with the necessary columns

    # Get New York session directions
    ny_dirs_mag_na = sessions_df.loc[(slice(None), 'NewYork'), ['Direction']].reset_index()
    ny_dirs_mag_na['Date'] = ny_dirs_mag_na['Date'] + pd.Timedelta(days=1) # Shift date forward by 1 day
    ny_dirs_mag_na = ny_dirs_mag_na.rename(columns={'Direction': 'Previous_NY_Direction'})

    # Get Asia session direction and range
    asia_data_mag_na = sessions_df.loc[(slice(None), 'Asia'), ['Direction', 'Range']].reset_index()
    asia_data_mag_na = asia_data_mag_na.rename(columns={'Direction': 'Asia_Direction', 'Range': 'Asia_Range'})

    # Merge on Date (which is Asia's Date)
    merged_mag_na = pd.merge(
        asia_data_mag_na,
        ny_dirs_mag_na,
        on='Date',
        how='inner' # Only include dates where both a preceding NY and the current Asia session exist
    )

    # Filter for instances where:
    # 1. Previous NY had a directional move (not flat)
    # 2. Asia's direction matched Previous NY's direction
    continuation_days_mag_na = merged_mag_na[
        (merged_mag_na['Previous_NY_Direction'] != 0) & # Filter out flat Previous NY sessions
        (merged_mag_na['Previous_NY_Direction'] == merged_mag_na['Asia_Direction']) # Filter for continuation
    ].copy() # Use .copy() to avoid SettingWithCopyWarning

    # Calculate the average Asia Range on these continuation days
    if not continuation_days_mag_na.empty:
        average_asia_range_on_continuation = continuation_days_mag_na['Asia_Range'].mean()
        print(f"Analysis Period: {merged_mag_na['Date'].min()} to {merged_mag_na['Date'].max()}")
        print(f"Total instances where Previous NY had direction and Asia continued it: {len(continuation_days_mag_na)}")
        print(f"Average Asia session range on days it continued Previous NY's trend: {average_asia_range_on_continuation:.2f}")

        # --- Add context by comparing to overall Asia range and reversal range ---

        # Overall average Asia range (for comparison)
        overall_average_asia_range = asia_data_mag_na['Asia_Range'].mean()
        print(f"Overall average Asia session range (all instances): {overall_average_asia_range:.2f}")

        # Average Asia range on reversal days (for comparison)
        reversal_days_mag_na = merged_mag_na[
            (merged_mag_na['Previous_NY_Direction'] != 0) & # Previous NY must have direction
            (merged_mag_na['Asia_Direction'] != 0) & # Asia must have direction
            (merged_mag_na['Previous_NY_Direction'] != merged_mag_na['Asia_Direction']) # Directions are opposite
        ].copy()

        if not reversal_days_mag_na.empty:
             average_asia_range_on_reversal = reversal_days_mag_na['Asia_Range'].mean()
             print(f"Average Asia session range on days it reversed Previous NY's trend ({len(reversal_days_mag_na)} instances): {average_asia_range_on_reversal:.2f}")
        else:
            print("Not enough instances found where Asia clearly reversed a directional Previous NY trend to calculate average reversal range.")

    else:
        print("Not enough instances found where Asia continued Previous NY's trend to calculate average range.")

except Exception as e:
    print(f"An error occurred during the magnitude analysis: {e}")

print("--- Magnitude Analysis Complete ---")