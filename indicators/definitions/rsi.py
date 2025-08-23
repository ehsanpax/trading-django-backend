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
    NAME = "RSI"
    VERSION = 1
    PANE_TYPE = 'pane'
    OUTPUTS = ["rsi"]
<<<<<<< Updated upstream
    # Visual metadata for frontend UI
    VISUAL_SCHEMA = {
        "series": {
            "rsi": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"},
            }
        },
        "guides": {
            "upper": {
                "value": {"type": "number"},
                "color": {"type": "string"},
                "visible": {"type": "boolean"}
            },
            "lower": {
                "value": {"type": "number"},
                "color": {"type": "string"},
                "visible": {"type": "boolean"}
            },
            "middle": {
                "value": {"type": "number"},
                "color": {"type": "string"},
                "visible": {"type": "boolean"}
            }
        }
    }
    VISUAL_DEFAULTS = {
        "series": {
            "rsi": {"color": "#800080", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True}
        },
        "guides": {
            "upper": {"value": 70, "color": "#808080", "visible": True},
            "lower": {"value": 30, "color": "#808080", "visible": True},
            "middle": {"value": 50, "color": "#d3d3d3", "visible": False}
        }
    }
=======
>>>>>>> Stashed changes
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
