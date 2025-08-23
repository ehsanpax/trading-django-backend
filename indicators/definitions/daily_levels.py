from typing import Dict, List
import pandas as pd
from core.interfaces import IndicatorInterface
import logging

logger = logging.getLogger(__name__)

class DailyLevelsIndicator:
    """
    Draws lines for daily high, low, open, and previous day's high/low.
    Conforms to the IndicatorInterface.
    """
    NAME = "DailyLevels"
    VERSION = 1
<<<<<<< Updated upstream
    PANE_TYPE = 'overlay'
    OUTPUTS = ["high_of_day", "low_of_day", "day_open", "prev_day_high", "prev_day_low"]
    # Visual metadata
    VISUAL_SCHEMA = {
        "series": {
            "high_of_day": {"color": {"type": "string"}, "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]}, "lineWidth": {"type": "integer", "min": 1, "max": 5}, "visible": {"type": "boolean"}},
            "low_of_day": {"color": {"type": "string"}, "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]}, "lineWidth": {"type": "integer", "min": 1, "max": 5}, "visible": {"type": "boolean"}},
            "day_open": {"color": {"type": "string"}, "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]}, "lineWidth": {"type": "integer", "min": 1, "max": 5}, "visible": {"type": "boolean"}},
            "prev_day_high": {"color": {"type": "string"}, "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]}, "lineWidth": {"type": "integer", "min": 1, "max": 5}, "visible": {"type": "boolean"}},
            "prev_day_low": {"color": {"type": "string"}, "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]}, "lineWidth": {"type": "integer", "min": 1, "max": 5}, "visible": {"type": "boolean"}}
        }
    }
    VISUAL_DEFAULTS = {
        "series": {
            "high_of_day": {"color": "#008000", "lineStyle": "solid", "lineWidth": 1, "visible": True},
            "low_of_day": {"color": "#ff0000", "lineStyle": "solid", "lineWidth": 1, "visible": True},
            "day_open": {"color": "#0000ff", "lineStyle": "dotted", "lineWidth": 1, "visible": True},
            "prev_day_high": {"color": "#90ee90", "lineStyle": "dashed", "lineWidth": 1, "visible": True},
            "prev_day_low": {"color": "#f08080", "lineStyle": "dashed", "lineWidth": 1, "visible": True}
        }
    }
=======
    OUTPUTS = ["high_of_day", "low_of_day", "day_open", "prev_day_high", "prev_day_low"]
>>>>>>> Stashed changes
    PARAMS_SCHEMA = {
        "show_high": {"type": "boolean", "default": True, "ui_only": True, "display_name": "Show Day's High"},
        "show_low": {"type": "boolean", "default": True, "ui_only": True, "display_name": "Show Day's Low"},
        "show_open": {"type": "boolean", "default": True, "ui_only": True, "display_name": "Show Day's Open"},
        "show_prev_high": {"type": "boolean", "default": True, "ui_only": True, "display_name": "Show Previous Day's High"},
        "show_prev_low": {"type": "boolean", "default": True, "ui_only": True, "display_name": "Show Previous Day's Low"},
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the daily levels.
        """
        if not isinstance(ohlcv.index, pd.DatetimeIndex):
            logger.error("Data must have a DatetimeIndex for DailyLevelsIndicator.")
            return {}

        data = ohlcv.copy()
        if data.index.tz is None:
            data.index = data.index.tz_localize('UTC')
        else:
            data.index = data.index.tz_convert('UTC')

        data['date'] = data.index.date
        
        daily_data = data.groupby('date').agg(
            daily_open=('open', 'first'),
            daily_high=('high', 'max'),
            daily_low=('low', 'min')
        )

        daily_data['prev_daily_high'] = daily_data['daily_high'].shift(1)
        daily_data['prev_daily_low'] = daily_data['daily_low'].shift(1)

        data = data.join(daily_data, on='date')

        data['current_day_high'] = data.groupby('date')['high'].cummax()
        data['current_day_low'] = data.groupby('date')['low'].cummin()

        output = {}
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

# Static check for protocol adherence
_t: IndicatorInterface = DailyLevelsIndicator()
