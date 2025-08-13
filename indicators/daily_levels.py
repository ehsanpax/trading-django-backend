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
    VERSION = 1
    OUTPUTS = ["high_of_day", "low_of_day", "day_open", "prev_day_high", "prev_day_low"]
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
