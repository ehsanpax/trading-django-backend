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
        'Asia': (pd.Timedelta(hours=0), pd.Timedelta(hours=8, minutes=0)),
        'London': (pd.Timedelta(hours=8), pd.Timedelta(hours=13, minutes=0)),
        'NewYork': (pd.Timedelta(hours=13, minutes=0), pd.Timedelta(hours=22, minutes=0))
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

print("\n--- Analyzing London Up-trend followed by NY Reversal below London Low ---")

try:
    # Get necessary data for London sessions (Direction and Low)
    london_data_cond = sessions_df.loc[(slice(None), 'London'), ['Direction', 'Low']].reset_index()

    # Get necessary data for New York sessions (Direction and Close)
    newyork_data_cond = sessions_df.loc[(slice(None), 'NewYork'), ['Direction', 'Close']].reset_index()

    # Rename columns for clarity after merging
    london_data_cond = london_data_cond.rename(columns={
        'Direction': 'London_Direction',
        'Low': 'London_Low'
    })
    newyork_data_cond = newyork_data_cond.rename(columns={
        'Direction': 'NewYork_Direction',
        'Close': 'NewYork_Close'
    })

    # Merge the London and New York dataframes on the 'Date' to align sessions on the same day
    merged_conditional = pd.merge(
        london_data_cond,
        newyork_data_cond,
        on='Date',
        how='inner' # Only consider days where both a London and New York session exist
    )

    # --- Define the Base for the Percentage (Denominator) ---
    # We are interested in the percentage *of the days that London has trended up*.
    # So, the denominator is the total count of days where London's direction was +1 (Up).
    london_up_days = merged_conditional[merged_conditional['London_Direction'] == 1].copy()
    total_london_up_days = len(london_up_days)

    # --- Define the Specific Event (Numerator) ---
    # We want to count the days from the 'london_up_days' set that *also* meet the other conditions:
    # 1. New York reversed (Direction == -1)
    # 2. New York closed below London's Low (NewYork_Close < London_Low)
    specific_event_days = london_up_days[
        (london_up_days['NewYork_Direction'] == -1) & # NY reversed (went down relative to its open)
        (london_up_days['NewYork_Close'] < london_up_days['London_Low']) # NY's close price is below London's lowest price
    ].copy() # Use .copy() to avoid SettingWithCopyWarning

    count_specific_event = len(specific_event_days)

    # --- Calculate the Percentage ---
    if total_london_up_days > 0:
        percentage_specific_event = (count_specific_event / total_london_up_days) * 100

        print(f"Analysis Period: {merged_conditional['Date'].min()} to {merged_conditional['Date'].max()}")
        print(f"Total days London trended up (with corresponding NY session): {total_london_up_days}")
        print(f"Days meeting specific conditions (London Up, NY Reversed, NY Closed below London Low): {count_specific_event}")
        print(f"Percentage of London up-days where NY reversed and closed below London's low: {percentage_specific_event:.2f}%")

    else:
        print("No days found where London trended up to perform this analysis.")


except Exception as e:
    print(f"An error occurred during the analysis: {e}")

print("--- Analysis Complete ---")