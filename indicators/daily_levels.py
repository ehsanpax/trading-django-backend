from bots.base import BaseIndicator, BotParameter
from bots.registry import register_indicator
from typing import List, Any, Dict
import pandas as pd
import numpy as np

class DailyLevelsIndicator(BaseIndicator):
    NAME = "daily_levels"
    DISPLAY_NAME = "Daily Levels"
    DESCRIPTION = "Draws lines for daily high, low, open, and previous day's high/low."
    PANE_TYPE = "overlay"  # This will make it an overlay on the main chart

    PARAMETERS: List[BotParameter] = [
        # High of the day
        BotParameter("show_high", "bool", "Show Day's High", "Show the high of the day line.", True),
        BotParameter("high_color", "str", "Day's High Color", "Color for the day's high line.", "green"),
        BotParameter("high_style", "enum", "Day's High Style", "Line style for the day's high.", "solid", options=["solid", "dashed", "dotted"]),
        BotParameter("high_width", "int", "Day's High Width", "Line width for the day's high.", 1, min_value=1, max_value=10),

        # Low of the day
        BotParameter("show_low", "bool", "Show Day's Low", "Show the low of the day line.", True),
        BotParameter("low_color", "str", "Day's Low Color", "Color for the day's low line.", "red"),
        BotParameter("low_style", "enum", "Day's Low Style", "Line style for the day's low.", "solid", options=["solid", "dashed", "dotted"]),
        BotParameter("low_width", "int", "Day's Low Width", "Line width for the day's low.", 1, min_value=1, max_value=10),

        # Day's open
        BotParameter("show_open", "bool", "Show Day's Open", "Show the day's open line.", True),
        BotParameter("open_color", "str", "Day's Open Color", "Color for the day's open line.", "blue"),
        BotParameter("open_style", "enum", "Day's Open Style", "Line style for the day's open.", "dotted", options=["solid", "dashed", "dotted"]),
        BotParameter("open_width", "int", "Day's Open Width", "Line width for the day's open.", 1, min_value=1, max_value=10),

        # Previous day's high
        BotParameter("show_prev_high", "bool", "Show Previous Day's High", "Show the previous day's high line.", True),
        BotParameter("prev_high_color", "str", "Prev Day's High Color", "Color for the previous day's high line.", "lightgreen"),
        BotParameter("prev_high_style", "enum", "Prev Day's High Style", "Line style for the previous day's high.", "dashed", options=["solid", "dashed", "dotted"]),
        BotParameter("prev_high_width", "int", "Prev Day's High Width", "Line width for the previous day's high.", 1, min_value=1, max_value=10),

        # Previous day's low
        BotParameter("show_prev_low", "bool", "Show Previous Day's Low", "Show the previous day's low line.", True),
        BotParameter("prev_low_color", "str", "Prev Day's Low Color", "Color for the previous day's low line.", "lightcoral"),
        BotParameter("prev_low_style", "enum", "Prev Day's Low Style", "Line style for the previous day's low.", "dashed", options=["solid", "dashed", "dotted"]),
        BotParameter("prev_low_width", "int", "Prev Day's Low Width", "Line width for the previous day's low.", 1, min_value=1, max_value=10),
    ]

    def calculate(self, data: pd.DataFrame, **params) -> pd.DataFrame:
        """
        Calculates the daily levels and returns them as a DataFrame.
        """
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Data must have a DatetimeIndex.")

        # Ensure the index is localized to UTC for proper date handling
        if data.index.tz is None:
            data.index = data.index.tz_localize('UTC')
        else:
            data.index = data.index.tz_convert('UTC')

        # Group by date
        data['date'] = data.index.date
        
        # Calculate daily values
        daily_data = data.groupby('date').agg(
            daily_open=('open', 'first'),
            daily_high=('high', 'max'),
            daily_low=('low', 'min')
        )

        # Calculate previous day's values
        daily_data['prev_daily_high'] = daily_data['daily_high'].shift(1)
        daily_data['prev_daily_low'] = daily_data['daily_low'].shift(1)

        # Map daily values back to the original dataframe
        data = data.join(daily_data, on='date')

        # Calculate expanding high and low for the current day
        data['current_day_high'] = data.groupby('date')['high'].cummax()
        data['current_day_low'] = data.groupby('date')['low'].cummin()

        # Prepare the output DataFrame
        output = pd.DataFrame(index=data.index)
        
        if params.get("show_high"):
            output['high_of_day'] = data['current_day_high']
        if params.get("show_low"):
            output['low_of_day'] = data['current_day_low']
        if params.get("show_open"):
            output['day_open'] = data['daily_open']
        if params.get("show_prev_high"):
            output['prev_day_high'] = data['prev_daily_high']
        if params.get("show_prev_low"):
            output['prev_day_low'] = data['prev_daily_low']
            
        return output

    def required_history(self, **params) -> int:
        """
        Requires at least 2 days of data to calculate previous day's levels.
        Adding a small buffer.
        """
        return 2 * 1440 # Assuming 1-minute data, 2 days should be enough.

# Register the indicator
register_indicator(DailyLevelsIndicator.NAME, DailyLevelsIndicator)
