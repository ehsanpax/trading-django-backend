from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class OBVIndicator:
    """
    On-Balance Volume (OBV) Indicator.
    Conforms to the IndicatorInterface.
    """
    VERSION = 1
    OUTPUTS = ["obv"]
    PARAMS_SCHEMA = {
        "source": {
            "type": "string",
            "default": "close",
            "options": ["open", "high", "low", "close"],
            "ui_only": False,
            "display_name": "Source",
        }
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the On-Balance Volume (OBV).
        """
        source = params["source"]

        required_columns = [source, 'volume']
        for col in required_columns:
            if col not in ohlcv.columns:
                logger.error(f"Required column '{col}' not found in DataFrame for OBV calculation.")
                return {}

        try:
            obv_series = ta.obv(close=ohlcv[source], volume=ohlcv['volume'])
            if obv_series is None:
                raise ValueError("pandas_ta.obv returned None")
        except Exception as e:
            logger.error(f"Error calculating OBV: {e}", exc_info=True)
            return {}

        return {"obv": obv_series}

# Static check for protocol adherence
_t: IndicatorInterface = OBVIndicator()
