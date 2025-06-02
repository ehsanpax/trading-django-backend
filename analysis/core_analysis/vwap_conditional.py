import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

def _aggregate_to_sessions(df_resampled: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Aggregates resampled OHLCV data into defined trading sessions.
    `df_resampled` is the DataFrame already resampled to the target_timeframe.
    However, for session definition, we often work with a finer granularity like M1 or M5,
    or the target_timeframe itself if it's coarse enough (e.g. H1 for H1 sessions).
    This function assumes df_resampled is granular enough to define sessions accurately.
    If session analysis needs M1 base and target is H1, this function might need M1 data.
    For now, let's assume df_resampled is what we work with.
    """
    
    # Session times can be parameterized if needed, defaults here
    session_time_ranges_utc = {
        'Asia': (pd.Timedelta(hours=params.get('asia_start_hour', 0)), pd.Timedelta(hours=params.get('asia_end_hour', 7))),
        'London': (pd.Timedelta(hours=params.get('london_start_hour', 7)), pd.Timedelta(hours=params.get('london_end_hour', 14))),
        'NewYork': (pd.Timedelta(hours=params.get('newyork_start_hour', 14)), pd.Timedelta(hours=params.get('newyork_end_hour', 23)))
    }
    
    logger.info(f"Aggregating data into sessions. Input df shape: {df_resampled.shape}")
    if df_resampled.empty:
        return pd.DataFrame()

    session_list = []
    # Ensure index is UTC if not already (should be from processing)
    df_resampled.index = df_resampled.index.tz_convert('UTC') if df_resampled.index.tz is not None else df_resampled.index.tz_localize('UTC')
    
    all_dates_utc = df_resampled.index.normalize().unique()

    for day_utc in all_dates_utc:
        day_window_start = day_utc
        day_window_end = day_utc + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1) # Inclusive end of day
        
        data_for_day_window = df_resampled.loc[day_window_start : day_window_end]

        if data_for_day_window.empty:
            continue

        for session_name, (start_delta, end_delta) in session_time_ranges_utc.items():
            session_start_ts_utc = day_utc + start_delta
            # Session end is exclusive for filtering, but inclusive for data point if it lands exactly
            session_end_ts_utc = day_utc + end_delta 
            
            # Filter data for the specific session range
            # Slicing with loc includes both start and end if they exist in index
            session_data = data_for_day_window.loc[session_start_ts_utc : session_end_ts_utc]
            
            # Refine to ensure we don't overshoot into next session's start time due to resampling interval
            # e.g. if end_delta is 7 hours, and data is H1, the bar at 7:00 is the one we want.
            # If data is M15, bar at 06:45 is last for Asia if end is 07:00.
            # The .loc slice is usually sufficient.

            if session_data.empty:
                continue

            session_open = session_data['open'].iloc[0]
            session_high = session_data['high'].max()
            session_low = session_data['low'].min()
            session_close = session_data['close'].iloc[-1]
            session_volume = session_data['volume'].sum()
            session_range = session_high - session_low
            session_direction = 0
            if session_close > session_open: session_direction = 1
            elif session_close < session_open: session_direction = -1
            
            session_list.append({
                'Date': day_utc.date(), # Store as date object
                'Session': session_name,
                'OpenTime': session_data.index[0],
                'CloseTime': session_data.index[-1],
                'Open': session_open, 'High': session_high, 'Low': session_low, 'Close': session_close,
                'Volume': session_volume, 'Range': session_range, 'Direction': session_direction
            })
            
    sessions_df = pd.DataFrame(session_list)
    if not sessions_df.empty:
        sessions_df = sessions_df.set_index(['Date', 'Session']).sort_index()
    logger.info(f"Session aggregation complete. Sessions found: {len(sessions_df)}")
    return sessions_df

def _calculate_daily_vwap(df_ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Calculates Daily VWAP for every bar in df_ohlcv (assumed to be fine-grained, e.g., M1 or target_timeframe)."""
    logger.info(f"Calculating Daily VWAP. Input df shape: {df_ohlcv.shape}")
    if df_ohlcv.empty or not all(col in df_ohlcv.columns for col in ['high', 'low', 'close', 'volume']):
        logger.warning("Missing required columns for VWAP or empty DataFrame.")
        return df_ohlcv # Return as is, or an empty df with vwap column

    df = df_ohlcv.copy()
    df.index = df.index.tz_convert('UTC') if df.index.tz is not None else df.index.tz_localize('UTC')

    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['price_volume'] = df['typical_price'] * df['volume']
    df['date_utc'] = df.index.normalize()
    
    grouped_daily = df.groupby('date_utc')
    df['cum_volume_daily'] = grouped_daily['volume'].cumsum()
    df['cum_price_volume_daily'] = grouped_daily['price_volume'].cumsum()
    df['daily_vwap'] = df['cum_price_volume_daily'] / df['cum_volume_daily'].replace(0, np.nan)
    
    df.drop(columns=['typical_price', 'price_volume', 'date_utc', 'cum_volume_daily', 'cum_price_volume_daily'], inplace=True)
    logger.info("Daily VWAP calculation complete.")
    return df


def run_analysis(df_resampled_and_indicators: pd.DataFrame, **params) -> dict:
    """
    Main function for VWAP Conditional Analysis.
    `df_resampled_and_indicators` is the DataFrame after resampling to target_timeframe and adding any indicators.
    For this analysis, we need daily VWAP. If df_resampled_and_indicators is coarse (e.g. H1),
    calculating daily VWAP on it might not be as accurate as on M1.
    The original script calculated VWAP on M1 data.
    This function needs to decide:
    1. Use df_resampled_and_indicators directly for VWAP (if granular enough or acceptable).
    2. Or, it implies that M1 data should be passed or loaded separately for accurate daily VWAP.
       The current `run_analysis_job` task in the plan passes resampled data.
       Let's assume for now that `df_resampled_and_indicators` is used for VWAP calculation.
       This means if target_timeframe is H1, VWAP is calculated on H1 bars.
    """
    logger.info(f"Starting VWAP Conditional Analysis. Input df shape: {df_resampled_and_indicators.shape}, Params: {params}")

    if df_resampled_and_indicators.empty:
        logger.warning("Input DataFrame for VWAP Conditional Analysis is empty.")
        return {"error": "Input data is empty."}

    # Step 1: Calculate Daily VWAP on the provided DataFrame
    df_with_vwap = _calculate_daily_vwap(df_resampled_and_indicators.copy())
    if 'daily_vwap' not in df_with_vwap.columns:
        logger.error("Failed to calculate daily VWAP.")
        return {"error": "Failed to calculate daily VWAP."}

    # Step 2: Aggregate data into sessions (using the same df_with_vwap)
    sessions_df = _aggregate_to_sessions(df_with_vwap.copy(), params)
    if sessions_df.empty:
        logger.warning("No sessions could be aggregated from the data.")
        return {"error": "No sessions could be aggregated."}

    # Step 3: Merge VWAP at session close times into sessions_df
    sessions_df_reset = sessions_df.reset_index().copy()
    # Ensure CloseTime is unique for merging, drop duplicates if any (unlikely for sessions)
    sessions_df_reset = sessions_df_reset.drop_duplicates(subset=['CloseTime'])

    # Merge with daily_vwap from df_with_vwap (which has VWAP for every bar of target_timeframe)
    # We need VWAP at the specific CloseTime of each session.
    session_vwap_data = pd.merge(
        sessions_df_reset,
        df_with_vwap[['daily_vwap']], # Select only the vwap column from the main df
        left_on='CloseTime',      # Merge using the session's close time
        right_index=True,         # Merge with the index (timestamp) of df_with_vwap
        how='left'
    )
    session_vwap_data.rename(columns={'daily_vwap': 'VWAP_at_Close'}, inplace=True)

    # Determine "Close vs. VWAP" Condition
    conditions = [
        session_vwap_data['Close'] > session_vwap_data['VWAP_at_Close'],
        session_vwap_data['Close'] < session_vwap_data['VWAP_at_Close'],
        session_vwap_data['Close'] == session_vwap_data['VWAP_at_Close']
    ]
    choices = ['Closed_Above_VWAP', 'Closed_Below_VWAP', 'Closed_At_VWAP']
    session_vwap_data['Close_vs_VWAP'] = np.select(conditions, choices, default='VWAP_Not_Available')
    session_vwap_data.loc[session_vwap_data['VWAP_at_Close'].isna(), 'Close_vs_VWAP'] = 'VWAP_Not_Available'
    
    logger.info(f"session_vwap_data shape after VWAP/Condition: {session_vwap_data.shape}")

    # Step 4: Link Previous Session's VWAP Condition to Next Session's Direction
    all_transitions_list = []
    final_cols_order = ['Previous_Session_Date', 'Previous_Session_Type', 'Previous_Close_vs_VWAP',
                        'Next_Session_Date', 'Next_Session_Type', 'Next_Session_Direction']

    # Asia (Prev) -> London (Next)
    asia_prev = session_vwap_data[session_vwap_data['Session'] == 'Asia'][['Date', 'Session', 'Close_vs_VWAP']]
    london_next = session_vwap_data[session_vwap_data['Session'] == 'London'][['Date', 'Session', 'Direction']]
    al_transitions = pd.merge(asia_prev, london_next, on='Date', how='inner', suffixes=('_Prev', '_Next'))
    if not al_transitions.empty:
        al_transitions.rename(columns={'Date': 'Previous_Session_Date', 'Session_Prev': 'Previous_Session_Type', 
                                   'Close_vs_VWAP': 'Previous_Close_vs_VWAP', 'Session_Next': 'Next_Session_Type', 
                                   'Direction': 'Next_Session_Direction'}, inplace=True)
        al_transitions['Next_Session_Date'] = al_transitions['Previous_Session_Date']
        all_transitions_list.append(al_transitions[final_cols_order])

    # London (Prev) -> New York (Next)
    london_prev = session_vwap_data[session_vwap_data['Session'] == 'London'][['Date', 'Session', 'Close_vs_VWAP']]
    ny_next = session_vwap_data[session_vwap_data['Session'] == 'NewYork'][['Date', 'Session', 'Direction']]
    lny_transitions = pd.merge(london_prev, ny_next, on='Date', how='inner', suffixes=('_Prev', '_Next'))
    if not lny_transitions.empty:
        lny_transitions.rename(columns={'Date': 'Previous_Session_Date', 'Session_Prev': 'Previous_Session_Type', 
                                      'Close_vs_VWAP': 'Previous_Close_vs_VWAP', 'Session_Next': 'Next_Session_Type', 
                                      'Direction': 'Next_Session_Direction'}, inplace=True)
        lny_transitions['Next_Session_Date'] = lny_transitions['Previous_Session_Date']
        all_transitions_list.append(lny_transitions[final_cols_order])

    # New York (Prev) -> Asia (Next)
    ny_prev = session_vwap_data[session_vwap_data['Session'] == 'NewYork'][['Date', 'Session', 'Close_vs_VWAP']]
    asia_next_shifted = session_vwap_data[session_vwap_data['Session'] == 'Asia'].copy()
    asia_next_shifted['Date_Match_Prev_NY'] = asia_next_shifted['Date'] - pd.Timedelta(days=1)
    
    nya_transitions = pd.merge(ny_prev, asia_next_shifted[['Date', 'Date_Match_Prev_NY', 'Session', 'Direction']],
                               left_on='Date', right_on='Date_Match_Prev_NY', how='inner', suffixes=('_Prev', '_Next'))
    if not nya_transitions.empty:
        nya_transitions.rename(columns={'Date_Prev': 'Previous_Session_Date', 'Session_Prev': 'Previous_Session_Type',
                                      'Close_vs_VWAP': 'Previous_Close_vs_VWAP', 'Date_Next': 'Next_Session_Date', 
                                      'Session_Next': 'Next_Session_Type', 'Direction': 'Next_Session_Direction'}, inplace=True)
        all_transitions_list.append(nya_transitions[final_cols_order])

    if not all_transitions_list:
        logger.warning("No session transitions found for analysis.")
        return {"error": "No session transitions found."}

    analysis_df = pd.concat(all_transitions_list, ignore_index=True)
    logger.info(f"Final analysis_df shape: {analysis_df.shape}")

    # Step 5: Calculate conditional probabilities / counts
    results = {}
    prev_session_types = ['Asia', 'London', 'NewYork']
    vwap_conditions_order = ['Closed_Above_VWAP', 'Closed_Below_VWAP', 'Closed_At_VWAP', 'VWAP_Not_Available']

    for prev_type in prev_session_types:
        results[prev_type] = {}
        transitions_from_prev = analysis_df[analysis_df['Previous_Session_Type'] == prev_type]
        if transitions_from_prev.empty:
            continue
        
        for condition in vwap_conditions_order:
            condition_group = transitions_from_prev[transitions_from_prev['Previous_Close_vs_VWAP'] == condition]
            if condition_group.empty:
                results[prev_type][condition] = {"total_transitions": 0, "next_direction_counts": {}, "next_direction_percentages": {}}
                continue

            next_dir_counts = condition_group['Next_Session_Direction'].value_counts().sort_index()
            next_dir_perc = (next_dir_counts / next_dir_counts.sum() * 100).round(2)
            
            results[prev_type][condition] = {
                "total_transitions": int(len(condition_group)),
                "next_session_type": condition_group['Next_Session_Type'].iloc[0] if not condition_group.empty else "N/A",
                "next_direction_counts": next_dir_counts.to_dict(),
                "next_direction_percentages": next_dir_perc.to_dict()
            }
    
    # Format for standardized output
    output_components = []
    overall_summary_lines = []

    for prev_session_type, conditions_data in results.items():
        session_summary = f"Transitions from {prev_session_type}:"
        table_rows = []
        for condition, data in conditions_data.items():
            if data["total_transitions"] > 0:
                line = f"  If {prev_session_type} {condition.replace('_', ' ').lower()}: {data['total_transitions']} cases. Next session ({data['next_session_type']}) direction percentages: {data['next_direction_percentages']}"
                overall_summary_lines.append(line)
                
                table_rows.append({
                    "condition": condition.replace('_', ' '),
                    "next_session": data['next_session_type'],
                    "up_perc": data['next_direction_percentages'].get(1.0, 0.0), # Handle float keys from value_counts
                    "down_perc": data['next_direction_percentages'].get(-1.0, 0.0),
                    "flat_perc": data['next_direction_percentages'].get(0.0, 0.0),
                    "total_transitions": data['total_transitions']
                })
        
        if table_rows:
            output_components.append({
                "type": "table",
                "title": f"{prev_session_type} VWAP Condition vs. Next Session Direction",
                "data": {
                    "columns": [
                        {"key": "condition", "label": f"{prev_session_type} Close vs VWAP"},
                        {"key": "next_session", "label": "Next Session Type"},
                        {"key": "up_perc", "label": "% Up"},
                        {"key": "down_perc", "label": "% Down"},
                        {"key": "flat_perc", "label": "% Flat"},
                        {"key": "total_transitions", "label": "Total Transitions"}
                    ],
                    "rows": table_rows
                }
            })

    final_output = {
        "analysis_display_name": "VWAP Conditional Analysis",
        "summary": "Analysis of next session direction based on previous session's close relative to daily VWAP.\n" + "\n".join(overall_summary_lines),
        "parameters_used": params, # Echo back any parameters used
        "components": output_components
    }
            
    logger.info("VWAP Conditional Analysis complete.")
    return final_output

# Example of how this might be called (for conceptual understanding):
# if __name__ == '__main__':
#     # This would require setting up a dummy df_resampled_and_indicators
#     # For example, load from a CSV, resample, etc.
#     # df_m1 = pd.read_csv("path_to_m1_data.csv", index_col='time', parse_dates=True)
#     # df_h1 = resample_data(df_m1, "1H") # Assuming resample_data is in this file or imported
#     # df_h1_with_indicators = calculate_all_indicators(df_h1) # Assuming this is also available
#     # analysis_output = run_analysis(df_h1_with_indicators, asia_start_hour=0, asia_end_hour=8) # Example param
#     # print(analysis_output)
#     pass
