from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class RSIIndicator:
    """
    Relative Strength Index (RSI) Indicator.
    Conforms to the IndicatorInterface.
    """
    VERSION = 1
    OUTPUTS = ["rsi"]
    PARAMS_SCHEMA = {
        "length": {
            "type": "integer",
            "default": 14,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Length",
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
        Calculates the Relative Strength Index (RSI).
        """
        length = params["length"]
        source = params["source"]

        if source not in ohlcv.columns:
            logger.error(f"Source column '{source}' not found in DataFrame for RSI calculation.")
            return {}

        try:
            rsi_series = ta.rsi(close=ohlcv[source], length=length)
            if rsi_series is None:
                raise ValueError("pandas_ta.rsi returned None")
        except Exception as e:
            logger.error(f"Error calculating RSI: {e}", exc_info=True)
            return {}

        return {"rsi": rsi_series}

# Static check for protocol adherence
_t: IndicatorInterface = RSIIndicator()
