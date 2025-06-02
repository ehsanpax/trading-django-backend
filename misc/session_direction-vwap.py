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


import pandas as pd
import numpy as np

# Assuming df (original 1-min data) and sessions_df (aggregated session data)
# from previous steps are already loaded and ready

print("\n--- Running Step 14 (Final Corrected): VWAP Calculation and Linking Transitions ---")

# Check if df and sessions_df are available before proceeding
if 'df' not in locals() or df.empty:
    print("Error: Original DataFrame 'df' is not available or is empty. Cannot proceed with VWAP analysis.")
    analysis_ready_vwap = pd.DataFrame() # Ensure this is set to empty if error
elif 'sessions_df' not in locals() or sessions_df.empty:
     print("Error: Aggregated DataFrame 'sessions_df' is not available or is empty. Cannot proceed with VWAP analysis.")
     analysis_ready_vwap = pd.DataFrame() # Ensure this is set to empty if error
else:
    print(f"Input df shape: {df.shape}")
    print(f"Input sessions_df shape: {sessions_df.shape}")
    # print(f"sessions_df head:\n{sessions_df.head()}") # Uncomment for debugging input sessions_df


    print("\n--- Calculating Daily VWAP Minute-by-Minute ---")
    try:
        # --- 1. Calculate Daily VWAP for every minute ---
        # Ensure original df index is sorted by time - CRITICAL for cumulative sums
        df = df.sort_index()

        # Calculate typical price for each 1-minute bar: (High + Low + Close) / 3
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3

        # Calculate (Typical Price * Volume) for each bar
        df['price_volume'] = df['typical_price'] * df['volume']

        # Group the data by UTC calendar day
        df['date_utc'] = df.index.normalize() # Extracts the date part (00:00 UTC)
        grouped_daily = df.groupby('date_utc')

        # Calculate cumulative sum of Volume and (Price * Volume) within each day's group
        # cumsum() requires the index to be sorted within groups, which groupby ensures by default if df is sorted
        df['cum_volume_daily'] = grouped_daily['volume'].cumsum()
        df['cum_price_volume_daily'] = grouped_daily['price_volume'].cumsum()

        # Calculate Daily VWAP
        # Avoid division by zero if cumulative volume is 0
        df['daily_vwap'] = df['cum_price_volume_daily'] / df['cum_volume_daily'].replace(0, np.nan) # np.nan is used here

        # Drop temporary columns
        df = df.drop(columns=['typical_price', 'price_volume', 'date_utc', 'cum_volume_daily', 'cum_price_volume_daily'])

        print("Daily VWAP calculated successfully for all minutes.")
        # print(df[['daily_vwap']].dropna().head()) # Debugging: show some calculated VWAP values


    except Exception as e:
        print(f"An error occurred during daily VWAP calculation: {e}")
        # If VWAP calculation fails, we cannot proceed with the analysis
        df = pd.DataFrame() # Set df to empty if calculation fails


    print("\n--- Linking Previous Session's VWAP Condition to Next Session's Direction (Separate Merges) ---")

    # Check if df was successfully created/updated before proceeding
    if 'daily_vwap' not in df.columns or df.empty:
        print("Error: Daily VWAP calculation failed or original DataFrame is empty. Cannot proceed with linking.")
        analysis_ready_vwap = pd.DataFrame() # Ensure this is set to empty if error
    else:
        try:
            # --- Get VWAP at Session Closes and Determine Close vs VWAP Condition for ALL sessions ---
            # Merge sessions_df with the calculated daily_vwap from df, using the CloseTime as the key

            # Reset index of sessions_df to use Date and Session as columns
            sessions_df_reset = sessions_df.reset_index().copy() # Use copy defensively
            # Ensure sessions_df_reset CloseTime is unique for merging (should be unique by definition, but safety)
            # This might remove one row if CloseTimes are identical, but unlikely for sessions
            sessions_df_reset = sessions_df_reset.drop_duplicates(subset=['CloseTime'])


            # Merge sessions_df_reset with df[['daily_vwap']], using the CloseTime timestamp as the merge key
            session_vwap_data = pd.merge(
                sessions_df_reset,
                df[['daily_vwap']],
                left_on='CloseTime',
                right_index=True, # Merge using the index (timestamp) of df
                how='left' # Use a left merge to keep all sessions, add VWAP where the CloseTime matches a timestamp in df
            )

            # Rename the merged column
            session_vwap_data = session_vwap_data.rename(columns={'daily_vwap': 'VWAP_at_Close'})

            # Determine "Close vs. VWAP" Condition for Each Session
            conditions_vwap = [
                session_vwap_data['Close'] > session_vwap_data['VWAP_at_Close'],
                session_vwap_data['Close'] < session_vwap_data['VWAP_at_Close'],
                session_vwap_data['Close'] == session_vwap_data['VWAP_at_Close']
            ]
            choices_vwap = ['Closed_Above_VWAP', 'Closed_Below_VWAP', 'Closed_At_VWAP']

            session_vwap_data['Close_vs_VWAP'] = np.select(conditions_vwap, choices_vwap, default='VWAP_Not_Available') # np.select is used here
            session_vwap_data.loc[session_vwap_data['VWAP_at_Close'].isna(), 'Close_vs_VWAP'] = 'VWAP_Not_Available' # Explicitly handle NaN VWAP


            print(f"session_vwap_data shape after VWAP/Condition: {session_vwap_data.shape}")
            # print(f"session_vwap_data head:\n{session_vwap_data.head()}") # Uncomment for debugging


            # --- 4. Link Previous Session's VWAP Condition to Next Session's Direction (Separate Merges) ---

            all_transitions_list = []

            # --- Asia (Previous) -> London (Next) ---
            # Previous session data: Asia, need Date, Session, Close_vs_VWAP
            asia_sessions_prev = session_vwap_data[session_vwap_data['Session'] == 'Asia'].copy()
            # Next session data: London, need Date, Session, Direction
            london_sessions_next = session_vwap_data[session_vwap_data['Session'] == 'London'].copy()

            # Merge Asia (Day N) with London (Day N) on Date
            al_transitions = pd.merge(
                asia_sessions_prev[['Date', 'Session', 'Close_vs_VWAP']], # From Asia sessions (Day N)
                london_sessions_next[['Date', 'Session', 'Direction']], # From London sessions (Day N)
                on='Date',
                how='inner' # Only where both exist on the same day
            )
            # Rename columns to the final required format
            al_transitions = al_transitions.rename(columns={
                'Date': 'Previous_Session_Date', # Date of previous session
                'Session_x': 'Previous_Session_Type',
                'Close_vs_VWAP': 'Previous_Close_vs_VWAP',
                # 'Date': 'Next_Session_Date', # Next session is same day
                'Session_y': 'Next_Session_Type',
                'Direction': 'Next_Session_Direction'
            })
            # Add Next_Session_Date column, which is the same as Previous_Session_Date for AL
            al_transitions['Next_Session_Date'] = al_transitions['Previous_Session_Date']

            # Select and reorder columns to match the final desired structure
            final_cols_order_for_transition = ['Previous_Session_Date', 'Previous_Session_Type', 'Previous_Close_vs_VWAP',
                                               'Next_Session_Date', 'Next_Session_Type', 'Next_Session_Direction']
            al_transitions = al_transitions[final_cols_order_for_transition]


            all_transitions_list.append(al_transitions)


            # --- London (Previous) -> New York (Next) ---
            # Previous session data: London, need Date, Session, Close_vs_VWAP
            london_sessions_prev = session_vwap_data[session_vwap_data['Session'] == 'London'].copy()
            # Next session data: New York, need Date, Session, Direction
            newyork_sessions_next = session_vwap_data[session_vwap_data['Session'] == 'NewYork'].copy()

            # Merge London (Day N) with New York (Day N) on Date
            lny_transitions = pd.merge(
                london_sessions_prev[['Date', 'Session', 'Close_vs_VWAP']], # From London sessions (Day N)
                newyork_sessions_next[['Date', 'Session', 'Direction']], # From New York sessions (Day N)
                on='Date',
                how='inner' # Only where both exist on the same day
            )
            # Rename columns to the final required format
            lny_transitions = lny_transitions.rename(columns={
                'Date': 'Previous_Session_Date', # Date of previous session
                'Session_x': 'Previous_Session_Type',
                'Close_vs_VWAP': 'Previous_Close_vs_VWAP',
                # 'Date': 'Next_Session_Date', # Next session is same day
                'Session_y': 'Next_Session_Type',
                'Direction': 'Next_Session_Direction'
            })
            # Add Next_Session_Date column, which is the same as Previous_Session_Date for LNY
            lny_transitions['Next_Session_Date'] = lny_transitions['Previous_Session_Date']

            # Select and reorder columns to match the final desired structure
            lny_transitions = lny_transitions[final_cols_order_for_transition]


            all_transitions_list.append(lny_transitions)


            # --- New York (Previous) -> Asia (Next) ---
            # Previous session data: New York, need Date, Session, Close_vs_VWAP
            newyork_sessions_prev = session_vwap_data[session_vwap_data['Session'] == 'NewYork'].copy()
            # Next session data: Asia, need Date, Session, Direction
            asia_sessions_next = session_vwap_data[session_vwap_data['Session'] == 'Asia'].copy()

            # Shift Asia sessions Date back by 1 day to merge with previous day's NY
            # The 'Date' column in asia_sessions_next is the date of the Asia session (Day N+1)
            asia_sessions_next['Date_Match_Prev_NY'] = asia_sessions_next['Date'] - pd.Timedelta(days=1)

            # Merge New York (Day N) with Asia (Day N+1)
            # Merge key on NY side is 'Date' (Day N)
            # Merge key on Asia side is 'Date_Match_Prev_NY' (Day N)
            nya_transitions = pd.merge(
                newyork_sessions_prev[['Date', 'Session', 'Close_vs_VWAP']], # From New York sessions (Day N)
                asia_sessions_next[['Date', 'Date_Match_Prev_NY', 'Session', 'Direction']], # From Asia sessions (Day N+1)
                left_on='Date', # Merge using NY's Date (Day N)
                right_on='Date_Match_Prev_NY', # Merge using Asia's shifted date (Day N)
                how='inner' # Only where the NY session on Day N is followed by an Asia session on Day N+1
            )
            # Rename columns to the final required format
            # Date_x is NY's original date (Day N) -> Previous_Session_Date
            # Date_y is Asia's date (Day N+1) -> Next_Session_Date
            # Session_x is NY's Session -> Previous_Session_Type
            # Session_y is Asia's Session -> Next_Session_Type
            # Direction is Asia's Direction -> Next_Session_Direction
            nya_transitions = nya_transitions.rename(columns={
                'Date_x': 'Previous_Session_Date', # Date of previous session
                'Session_x': 'Previous_Session_Type',
                'Close_vs_VWAP': 'Previous_Close_vs_VWAP',
                'Date_y': 'Next_Session_Date', # Date of next session (Day N+1)
                'Session_y': 'Next_Session_Type',
                'Direction': 'Next_Session_Direction'
            })

            # Select and reorder columns to match the final desired structure
            nya_transitions = nya_transitions[final_cols_order_for_transition]


            all_transitions_list.append(nya_transitions)


            # --- Concatenate all transition types ---
            # Define the final required column order (consistent across all transition types)
            # final_columns_order = ['Previous_Session_Date', 'Previous_Session_Type', 'Previous_Close_vs_VWAP',
            #                        'Next_Session_Date', 'Next_Session_Type', 'Next_Session_Direction']

            # Concatenate the list of dataframes, which now all have consistent column names and order
            # Use ignore_index=True to create a new sequential index for the final DataFrame
            analysis_ready_vwap_revised = pd.concat(all_transitions_list, ignore_index=True)


            # --- Final DataFrame for Analysis and Sampling ---
            # This DataFrame should now have the exact columns needed by Step 16

            print(f"\nRevised analysis DataFrame shape: {analysis_ready_vwap_revised.shape}")
            print(f"Revised analysis DataFrame head:\n{analysis_ready_vwap_revised.head()}")
            print(f"Revised analysis DataFrame info:\n{analysis_ready_vwap_revised.info()}")
            # Check for missing values in critical columns
            print(f"Missing values in revised df:\n{analysis_ready_vwap_revised.isna().sum()}")


            # --- Pass the revised DataFrame to subsequent steps ---
            # The dataframe analysis_ready_vwap should now have the correct columns for Step 15/16
            analysis_ready_vwap = analysis_ready_vwap_revised # Use this name for compatibility


        except Exception as e:
            print(f"\nAn error occurred during the revised Step 14 linking: {e}")
            analysis_ready_vwap = pd.DataFrame() # Set to empty if error


# The Step 15 and Step 16 code blocks will follow this in your script

print("\n--- Analyzing Next Session Direction Conditional on Previous Session's Close vs. Daily VWAP (Broken Down by Previous Session Type) ---")

try:
    # Check if analysis_ready_vwap was successfully created in Step 14 and has the necessary columns
    required_analysis_cols_for_step15 = ['Previous_Session_Date', 'Previous_Session_Type', 'Previous_Close_vs_VWAP',
                                         'Next_Session_Date', 'Next_Session_Type', 'Next_Session_Direction']

    if 'analysis_ready_vwap' not in locals() or analysis_ready_vwap.empty or not all(col in analysis_ready_vwap.columns for col in required_analysis_cols_for_step15):
        print(f"Error: 'analysis_ready_vwap' DataFrame not found, is empty, or missing required columns ({required_analysis_cols_for_step15}). Please run the latest Step 14 first.")
    else:
        # Print summary info about the DataFrame being analyzed
        print(f"Analyzing DataFrame 'analysis_ready_vwap':")
        print(f"Shape: {analysis_ready_vwap.shape}")
        print(f"Columns: {analysis_ready_vwap.columns.tolist()}")
        print(f"First 5 rows:\n{analysis_ready_vwap.head()}")
        print(f"Info:\n{analysis_ready_vwap.info()}")


        # Define the order of previous session types to analyze
        previous_session_types = ['Asia', 'London', 'NewYork']

        # Define the order of VWAP conditions for consistent output
        vwap_conditions_order = ['Closed_Above_VWAP', 'Closed_Below_VWAP', 'Closed_At_VWAP', 'VWAP_Not_Available']


        # Iterate through each previous session type (Asia, London, New York)
        for prev_session_type in previous_session_types:
            print(f"\n=====================================================================")
            print(f"=== Analysis for transitions starting from {prev_session_type} sessions ===")
            print(f"=====================================================================")

            # Filter the analysis-ready data for transitions that started from this session type
            transitions_from_prev = analysis_ready_vwap[
                analysis_ready_vwap['Previous_Session_Type'] == prev_session_type
            ].copy() # Use copy to avoid SettingWithCopyWarning

            if transitions_from_prev.empty:
                print(f"No completed transitions found starting from {prev_session_type} sessions in the analysis period.")
                continue # Move to the next previous session type

            # Group this filtered data by the 'Previous_Close_vs_VWAP' condition of the PREVIOUS session
            # --- CORRECTED LINE: Use 'Previous_Close_vs_VWAP' ---
            vwap_condition_groups_by_session = transitions_from_prev.groupby('Previous_Close_vs_VWAP')

            print(f"Total {prev_session_type} session transitions analyzed: {len(transitions_from_prev)}")

            # Analyze each 'Previous_Close_vs_VWAP' condition group within this specific previous session type
            # Iterate through the conditions in a defined order for consistency
            for condition in vwap_conditions_order:
                 # Check if this specific condition group exists for this previous session type
                 if condition in vwap_condition_groups_by_session.groups:
                    group_df = vwap_condition_groups_by_session.get_group(condition)

                    if not group_df.empty:
                        print(f"\n--- When Previous {prev_session_type} Session Closed {condition} Daily VWAP ---")

                        # --- Debugging prints are kept but should now work ---
                        print(f"Debugging group_df size: {len(group_df)}")
                        print(f"Debugging group_df columns: {group_df.columns.tolist()}")
                        if 'Next_Session_Type' in group_df.columns:
                            print(f"Debugging Next_Session_Type dtype: {group_df['Next_Session_Type'].dtype}")
                            print(f"Debugging Next_Session_Type unique values: {group_df['Next_Session_Type'].unique()}")
                        if 'Next_Session_Direction' in group_df.columns:
                             print(f"Debugging Next_Session_Direction dtype: {group_df['Next_Session_Direction'].dtype}")
                             print(f"Debugging Next_Session_Direction unique values: {group_df['Next_Session_Direction'].unique()}")
                        # --- End Debugging Prints ---


                        # Get the type of the next session for clarity in output
                        # This should now work as Next_Session_Type column exists and is populated
                        if 'Next_Session_Type' in group_df.columns and not group_df['Next_Session_Type'].isna().all():
                             # Use the first non-NA value
                             next_session_type_example = group_df['Next_Session_Type'].dropna().iloc[0]
                        else:
                             next_session_type_example = "Unknown/Not Available" # Fallback


                        print(f"Next session type in this group is: {next_session_type_example}")
                        print(f"Total transitions in this group: {len(group_df)}")
                        print(f"{next_session_type_example} Session Direction Counts (-1=Down, 0=Flat, 1=Up):")

                        # Count directions of the NEXT session within this specific group
                        # This should now work as Next_Session_Direction column exists and is populated
                        if 'Next_Session_Direction' in group_df.columns:
                            # Use value_counts with dropna=False to include count of potential NaNs if any (should be 0)
                            next_direction_counts = group_df['Next_Session_Direction'].value_counts(dropna=False).sort_index()
                            print(next_direction_counts)

                            # Calculate percentages relative to the total in this specific condition group
                            next_direction_percentages = (next_direction_counts / next_direction_counts.sum() * 100).round(2)
                            print("\nPercentages:")
                            print(next_direction_percentages)
                        else:
                            print("Error: 'Next_Session_Direction' column missing for analysis.")


                    # No 'else: print("No transitions...")' needed here because we check if the condition group exists
                 # else:
                 #     # This block would print headers for groups that have 0 instances,
                 #     # useful for seeing which conditions never occurred. Can uncomment if desired.
                 #     # print(f"\n--- When Previous {prev_session_type} Session Closed {condition} Daily VWAP ---")
                 #     # print(f"No transitions found in this group.")
                 pass # Do nothing if the condition group doesn't exist for this session type


except Exception as e:
    # Catch the exception and print its details
    print(f"\nAn error occurred during the broken-down VWAP analysis: {e}")

print("\n--- Broken-Down Advanced Analysis Complete ---")


# Assuming analysis_ready_vwap DataFrame (with Previous_Session_Date, Next_Session_Date, Previous_Close_vs_VWAP)
# and session_vwap_data DataFrame (with full session details + VWAP_at_Close) from Step 14 are available

print("\n--- Providing Sample Data for Verification ---")

try:
    # Check if required DataFrames are available and have the necessary columns
    required_analysis_cols = ['Previous_Session_Date', 'Previous_Session_Type', 'Previous_Close_vs_VWAP',
                              'Next_Session_Date', 'Next_Session_Type', 'Next_Session_Direction']
    required_session_cols = ['Date', 'Session', 'OpenTime', 'CloseTime', 'Open', 'High', 'Low', 'Close', 'Volume', 'Range', 'Direction', 'VWAP_at_Close', 'Close_vs_VWAP']

    if 'analysis_ready_vwap' not in locals() or analysis_ready_vwap.empty or not all(col in analysis_ready_vwap.columns for col in required_analysis_cols):
        print(f"Error: 'analysis_ready_vwap' DataFrame not found, is empty, or missing required columns ({required_analysis_cols}). Please run the latest Step 14 first.")
    elif 'session_vwap_data' not in locals() or session_vwap_data.empty or not all(col in session_vwap_data.columns for col in required_session_cols):
         print(f"Error: 'session_vwap_data' DataFrame not found, is empty, or missing required columns ({required_session_cols}). Please run Step 14 first.")
    else:
        # Ensure date columns in both dataframes are datetime objects for consistent lookup
        analysis_ready_vwap['Previous_Session_Date'] = pd.to_datetime(analysis_ready_vwap['Previous_Session_Date'])
        analysis_ready_vwap['Next_Session_Date'] = pd.to_datetime(analysis_ready_vwap['Next_Session_Date'])
        session_vwap_data['Date'] = pd.to_datetime(session_vwap_data['Date'])


        # Define transition types to sample and number of samples per type
        transitions_to_sample = [
            ('Asia', 'London'),
            ('London', 'NewYork'),
            ('NewYork', 'Asia')
        ]
        num_samples_per_type = 3 # Number of examples for each transition type

        print(f"Sampling {num_samples_per_type} instances for each transition type:")

        # Iterate through each transition type
        for prev_type, next_type in transitions_to_sample:
            print(f"\n--- Samples for {prev_type} -> {next_type} Transitions ---")

            # Filter analysis_ready_vwap for this specific transition type
            transition_df = analysis_ready_vwap[
                (analysis_ready_vwap['Previous_Session_Type'] == prev_type) &
                (analysis_ready_vwap['Next_Session_Type'] == next_type)
            ]

            if transition_df.empty:
                print(f"No {prev_type} -> {next_type} transitions found in data to sample.")
                continue

            # Sample rows from the filtered DataFrame
            # Use random_state for reproducibility so you get the same samples each time you run
            sampled_transitions = transition_df.sample(min(num_samples_per_type, len(transition_df)), random_state=42)


            # Print details for each sampled transition
            for index, row in sampled_transitions.iterrows():
                prev_date = row['Previous_Session_Date'].date() # Get date part for printing
                prev_type_val = row['Previous_Session_Type']
                prev_close_vwap_cond = row['Previous_Close_vs_VWAP'] # Correct column name
                next_date = row['Next_Session_Date'].date() # Get date part for printing
                next_type_val = row['Next_Session_Type']
                next_direction_analysed = row['Next_Session_Direction']

                print(f"\nTransition Sample Details:")
                print(f"  Transition Type: {prev_type_val} -> {next_type_val}")
                print(f"  Date of Previous Session: {prev_date}")
                print(f"  Date of Next Session: {next_date}")
                print(f"  Analysed Next Direction: {next_direction_analysed}")
                print(f"  Analysed Prev Close vs VWAP Condition: {prev_close_vwap_cond}")


                # Look up and print details for the PREVIOUS session from session_vwap_data
                # Use the date and session type to find the matching row
                prev_session_details_lookup = session_vwap_data[
                     (session_vwap_data['Date'].dt.date == prev_date) & # Compare date parts
                     (session_vwap_data['Session'] == prev_type_val)
                ]

                if not prev_session_details_lookup.empty:
                     prev_s = prev_session_details_lookup.iloc[0]
                     print(f"  --- Previous Session Full Details ({prev_type_val} on {prev_date}) ---")
                     print(f"    OpenTime: {prev_s['OpenTime']}")
                     print(f"    CloseTime: {prev_s['CloseTime']}")
                     print(f"    Open: {prev_s['Open']:.4f}")
                     print(f"    High: {prev_s['High']:.4f}")
                     print(f"    Low: {prev_s['Low']:.4f}")
                     print(f"    Close: {prev_s['Close']:.4f}")
                     print(f"    Volume: {prev_s['Volume']}")
                     print(f"    Range: {prev_s['Range']:.4f}")
                     print(f"    Session Direction: {prev_s['Direction']}") # This is Previous Direction
                     print(f"    Daily VWAP at Close: {prev_s['VWAP_at_Close']:.4f}")
                     print(f"    Calculated Close vs VWAP: {prev_s['Close_vs_VWAP']}")
                     # Verification note
                     print(f"    VERIFY: Check if Previous Close ({prev_s['Close']:.4f}) is indeed {prev_close_vwap_cond.replace('_', ' ').lower()} Daily VWAP ({prev_s['VWAP_at_Close']:.4f}).")
                else:
                     print(f"  --- Previous Session Full Details ({prev_type_val} on {prev_date}) ---")
                     print("    Details not found in session_vwap_data (unexpected lookup failure).")


                # Look up and print details for the NEXT session from session_vwap_data
                # Use the date and session type to find the matching row
                next_session_details_lookup = session_vwap_data[
                    (session_vwap_data['Date'].dt.date == next_date) & # Compare date parts
                    (session_vwap_data['Session'] == next_type_val)
                ]

                if not next_session_details_lookup.empty:
                    next_s = next_session_details_lookup.iloc[0]
                    print(f"  --- Next Session Full Details ({next_type_val} on {next_date}) ---")
                    print(f"    OpenTime: {next_s['OpenTime']}")
                    print(f"    CloseTime: {next_s['CloseTime']}")
                    print(f"    Open: {next_s['Open']:.4f}")
                    print(f"    High: {next_s['High']:.4f}")
                    print(f"    Low: {next_s['Low']:.4f}")
                    print(f"    Close: {next_s['Close']:.4f}")
                    print(f"    Volume: {next_s['Volume']}")
                    print(f"    Range: {next_s['Range']:.4f}")
                    print(f"    Session Direction: {next_s['Direction']}") # This is Next Direction
                    # Verification note
                    print(f"    VERIFY: Check if Next Session Direction ({next_s['Direction']}) matches Analysed Next Direction ({next_direction_analysed}).")
                else:
                     print(f"  --- Next Session Full Details ({next_type_val} on {next_date}) ---")
                     print("    Details not found in session_vwap_data (unexpected lookup failure).")

                print("-" * 40) # Separator for samples

            print(f"\nSample data generation for {prev_type} -> {next_type} transitions complete.")


except Exception as e:
        print(f"\nAn error occurred during sample generation: {e}")

print("\n--- Sample Generation Complete ---")