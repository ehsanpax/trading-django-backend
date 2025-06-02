import pandas as pd

# Assuming sessions_df from Step 3 is already loaded and ready

print("\n--- Analyzing Asia to London Trend Continuation ---")

try:
    # 1. Separate Asia and London sessions
    asia_sessions = sessions_df.loc[(slice(None), 'Asia'), :] # Select all dates for 'Asia'
    london_sessions = sessions_df.loc[(slice(None), 'London'), :] # Select all dates for 'London'

    # Reset index to make 'Date' a regular column for merging
    asia_sessions = asia_sessions.reset_index()
    london_sessions = london_sessions.reset_index()

    # Rename Direction column to avoid conflict after merging
    asia_sessions = asia_sessions.rename(columns={'Direction': 'Asia_Direction'})
    london_sessions = london_sessions.rename(columns={'Direction': 'London_Direction'})

    # Keep only necessary columns for merging and comparison
    asia_sessions = asia_sessions[['Date', 'Asia_Direction']]
    london_sessions = london_sessions[['Date', 'London_Direction']]


    # 2. Align sessions by Date
    # Merge the two dataframes on the 'Date' column
    # This pairs the Asia session of a day with the London session of the same day
    merged_sessions = pd.merge(
        asia_sessions,
        london_sessions,
        on='Date',
        how='inner' # Only include dates where both Asia and London sessions exist
    )

    # 3. Compare Directions
    # Filter out instances where Asia session was flat (Direction == 0)
    directional_asia_london = merged_sessions[merged_sessions['Asia_Direction'] != 0].copy()

    # Check where London Direction matches Asia Direction
    continuation_matches = directional_asia_london[
        directional_asia_london['Asia_Direction'] == directional_asia_london['London_Direction']
    ]

    # 4. Calculate Percentage
    total_comparable_days = len(directional_asia_london)
    continuation_count = len(continuation_matches)

    if total_comparable_days > 0:
        continuation_percentage = (continuation_count / total_comparable_days) * 100
        print(f"Total days with directional Asia session & corresponding London session: {total_comparable_days}")
        print(f"Days where London continued Asia's trend: {continuation_count}")
        print(f"Percentage of times London continued Asia's trend: {continuation_percentage:.2f}%")
    else:
        print("Not enough comparable Asia and London sessions found to perform the analysis.")

except Exception as e:
    print(f"An error occurred during the analysis: {e}")

print("--- Analysis Complete ---")