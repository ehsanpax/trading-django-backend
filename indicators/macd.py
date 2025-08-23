from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class MACDIndicator:
    """
    Moving Average Convergence Divergence (MACD) Indicator.
    Conforms to the IndicatorInterface.
    """
    VERSION = 1
    OUTPUTS = ["macd", "histogram", "signal"]
    PARAMS_SCHEMA = {
        "fast_period": {
            "type": "integer",
            "default": 12,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Fast Period",
        },
        "slow_period": {
            "type": "integer",
            "default": 26,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Slow Period",
        },
        "signal_period": {
            "type": "integer",
            "default": 9,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Signal Period",
        },
        "source": {
            "type": "string",
            "default": "close",
            "options": ["open", "high", "low", "close"],
            "ui_only": False,
            "display_name": "Source",
        },
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the MACD, Signal Line, and MACD Histogram.
        """
        fast = params["fast_period"]
        slow = params["slow_period"]
        signal = params["signal_period"]
        source = params["source"]

        if source not in ohlcv.columns:
            logger.error(f"Source column '{source}' not found in DataFrame for MACD calculation.")
            return {}

        if fast >= slow:
            logger.error("Fast period must be less than slow period for MACD calculation.")
            return {}

        try:
            macd = ta.macd(close=ohlcv[source], fast=fast, slow=slow, signal=signal)
            if macd is None or macd.empty:
                raise ValueError("pandas_ta.macd returned None or empty DataFrame")

            output = {
                "macd": macd[f'MACD_{fast}_{slow}_{signal}'],
                "histogram": macd[f'MACDh_{fast}_{slow}_{signal}'],
                "signal": macd[f'MACDs_{fast}_{slow}_{signal}']
            }
        except Exception as e:
            logger.error(f"Error calculating MACD: {e}", exc_info=True)
            return {}

        return output

# Static check for protocol adherence
_t: IndicatorInterface = MACDIndicator()
