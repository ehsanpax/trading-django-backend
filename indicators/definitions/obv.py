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
    NAME = "OBV"
    VERSION = 1
    PANE_TYPE = 'pane'
    OUTPUTS = ["obv"]
    # Visual metadata
    VISUAL_SCHEMA = {
        "series": {
            "obv": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"}
            }
        },
        "guides": {
            "zero": {"value": {"type": "number"}, "color": {"type": "string"}, "visible": {"type": "boolean"}}
        }
    }
    VISUAL_DEFAULTS = {
        "series": {
            "obv": {"color": "#4682b4", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True}
        },
        "guides": {"zero": {"value": 0, "color": "#808080", "visible": False}}
    }
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
