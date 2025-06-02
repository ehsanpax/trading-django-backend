import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Assuming _aggregate_to_sessions might be a shared utility or defined here if not.
# For now, let's copy a simplified version or assume it's available.
# If it's in vwap_conditional.py, we might need to move it to a shared utils place.
# For simplicity in this step, let's assume sessions_df is passed or created similarly.

def _aggregate_to_sessions_for_trend(df_resampled: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    Simplified session aggregation for trend continuation.
    Focuses on getting session directions.
    """
    session_time_ranges_utc = {
        'Asia': (pd.Timedelta(hours=params.get('asia_start_hour', 0)), pd.Timedelta(hours=params.get('asia_end_hour', 7))),
        'London': (pd.Timedelta(hours=params.get('london_start_hour', 7)), pd.Timedelta(hours=params.get('london_end_hour', 14))),
        'NewYork': (pd.Timedelta(hours=params.get('newyork_start_hour', 14)), pd.Timedelta(hours=params.get('newyork_end_hour', 23)))
    }
    
    logger.info(f"TrendCont: Aggregating data into sessions. Input df shape: {df_resampled.shape}")
    if df_resampled.empty:
        return pd.DataFrame()

    session_list = []
    df_resampled.index = df_resampled.index.tz_convert('UTC') if df_resampled.index.tz is not None else df_resampled.index.tz_localize('UTC')
    all_dates_utc = df_resampled.index.normalize().unique()

    for day_utc in all_dates_utc:
        for session_name, (start_delta, end_delta) in session_time_ranges_utc.items():
            session_start_ts_utc = day_utc + start_delta
            session_end_ts_utc = day_utc + end_delta
            session_data = df_resampled.loc[session_start_ts_utc : session_end_ts_utc]

            if session_data.empty:
                continue

            session_open = session_data['open'].iloc[0]
            session_close = session_data['close'].iloc[-1]
            session_direction = 0
            if session_close > session_open: session_direction = 1
            elif session_close < session_open: session_direction = -1
            
            session_list.append({
                'Date': day_utc.date(),
                'Session': session_name,
                'Direction': session_direction
            })
            
    sessions_df = pd.DataFrame(session_list)
    if not sessions_df.empty:
        sessions_df = sessions_df.set_index(['Date', 'Session']).sort_index()
    logger.info(f"TrendCont: Session aggregation complete. Sessions found: {len(sessions_df)}")
    return sessions_df


def run_analysis(df_resampled_and_indicators: pd.DataFrame, **params) -> dict:
    """
    Main function for Trend Continuation Analysis.
    `df_resampled_and_indicators` is the DataFrame after resampling and indicators.
    `params` can include which sessions to compare, e.g., 
    `prev_session_name='Asia'`, `next_session_name='London'`.
    """
    prev_session_name = params.get('prev_session_name', 'Asia')
    next_session_name = params.get('next_session_name', 'London')

    logger.info(f"Starting Trend Continuation Analysis for {prev_session_name} -> {next_session_name}. Input df shape: {df_resampled_and_indicators.shape}")

    if df_resampled_and_indicators.empty:
        logger.warning("Input DataFrame for Trend Continuation Analysis is empty.")
        return {"error": "Input data is empty."}

    # Aggregate to sessions - this might be redundant if caller can provide sessionized data
    # Or, this analysis might always want to do its own session aggregation from resampled data.
    sessions_df = _aggregate_to_sessions_for_trend(df_resampled_and_indicators.copy(), params)
    if sessions_df.empty or sessions_df.index.nlevels < 2: # Expecting MultiIndex ('Date', 'Session')
        logger.warning("Session aggregation yielded no data or unexpected format.")
        return {"error": "Could not aggregate session data for trend analysis."}
        
    try:
        # Ensure 'Direction' column exists
        if 'Direction' not in sessions_df.columns:
            logger.error("'Direction' column not found in session data.")
            return {"error": "'Direction' column not found in session data."}

        # 1. Separate previous and next sessions
        # Using .xs to select from MultiIndex, robust against missing sessions on some dates
        prev_sessions = sessions_df.xs(prev_session_name, level='Session', drop_level=False)
        next_sessions = sessions_df.xs(next_session_name, level='Session', drop_level=False)
        
        if prev_sessions.empty or next_sessions.empty:
            logger.warning(f"Not enough {prev_session_name} or {next_session_name} sessions to compare.")
            return {
                "prev_session": prev_session_name, "next_session": next_session_name,
                "total_comparable_days": 0, "continuation_count": 0, "continuation_percentage": 0,
                "message": "Not enough session data for comparison."
            }

        # Reset index to make 'Date' a regular column for merging
        prev_sessions = prev_sessions.reset_index()
        next_sessions = next_sessions.reset_index()

        # Rename Direction column to avoid conflict
        prev_sessions = prev_sessions.rename(columns={'Direction': f'{prev_session_name}_Direction'})
        next_sessions = next_sessions.rename(columns={'Direction': f'{next_session_name}_Direction'})

        # Keep only necessary columns
        prev_sessions = prev_sessions[['Date', f'{prev_session_name}_Direction']]
        next_sessions = next_sessions[['Date', f'{next_session_name}_Direction']]

        # 2. Align sessions by Date
        merged_sessions = pd.merge(prev_sessions, next_sessions, on='Date', how='inner')

        if merged_sessions.empty:
            return {
                "prev_session": prev_session_name, "next_session": next_session_name,
                "total_comparable_days": 0, "continuation_count": 0, "continuation_percentage": 0,
                "message": "No matching dates found after merging sessions."
            }
            
        # 3. Compare Directions
        # Filter out instances where the previous session was flat
        directional_prev_session = merged_sessions[merged_sessions[f'{prev_session_name}_Direction'] != 0].copy()

        if directional_prev_session.empty:
            return {
                "prev_session": prev_session_name, "next_session": next_session_name,
                "total_comparable_days": 0, "continuation_count": 0, "continuation_percentage": 0,
                "message": f"No directional {prev_session_name} sessions found for comparison."
            }

        # Check where Next Session Direction matches Previous Session Direction
        continuation_matches = directional_prev_session[
            directional_prev_session[f'{prev_session_name}_Direction'] == directional_prev_session[f'{next_session_name}_Direction']
        ]

        # 4. Calculate Percentage
        total_comparable_days = len(directional_prev_session)
        continuation_count = len(continuation_matches)
        continuation_percentage = 0
        if total_comparable_days > 0:
            continuation_percentage = (continuation_count / total_comparable_days) * 100
        
        analysis_display_name = f"Trend Continuation: {prev_session_name} to {next_session_name}"
        summary_message = f"Analysis of {prev_session_name} trend continuation into {next_session_name} session."
        
        components = [
            {
                "type": "key_value_pairs",
                "title": "Trend Continuation Statistics",
                "data": [
                    {"key": "Previous Session", "value": prev_session_name},
                    {"key": "Next Session", "value": next_session_name},
                    {"key": "Total Comparable Days (Prev. Session Directional)", "value": total_comparable_days},
                    {"key": "Days Trend Continued", "value": continuation_count},
                    {"key": "Continuation Percentage", "value": f"{round(continuation_percentage, 2)}%"}
                ]
            }
        ]
        
        # Add a small table if there were comparable days
        if total_comparable_days > 0:
            table_data = {
                "columns": [
                    {"key": "metric", "label": "Metric"},
                    {"key": "value", "label": "Value"}
                ],
                "rows": [
                    {"metric": f"Directional {prev_session_name} Sessions", "value": total_comparable_days},
                    {"metric": f"{next_session_name} Continued Trend", "value": continuation_count},
                    {"metric": "Continuation Rate", "value": f"{round(continuation_percentage, 2)}%"}
                ]
            }
            components.append({
                "type": "table",
                "title": "Summary Table",
                "data": table_data
            })

        final_result = {
            "analysis_display_name": analysis_display_name,
            "summary": summary_message,
            "parameters_used": {
                "previous_session": prev_session_name,
                "next_session": next_session_name,
                # Potentially add date range or other relevant params from the job if available here
            },
            "components": components
        }
        logger.info(f"Trend Continuation Analysis results: {final_result}")
        return final_result

    except KeyError as e:
        logger.error(f"KeyError during trend continuation analysis: {e}. This might be due to missing session levels ('{prev_session_name}' or '{next_session_name}') in the data after filtering.")
        return {
            "analysis_display_name": f"Trend Continuation: {prev_session_name} to {next_session_name}",
            "summary": "Error during analysis.",
            "components": [{"type": "markdown_text", "data": f"Error: Data integrity issue, missing session data for {e}."}]
        }
    except Exception as e:
        logger.error(f"An unexpected error occurred during trend continuation analysis: {e}")
        return {
            "analysis_display_name": f"Trend Continuation: {prev_session_name} to {next_session_name}",
            "summary": "Error during analysis.",
            "components": [{"type": "markdown_text", "data": f"An unexpected error occurred: {str(e)}"}]
        }
