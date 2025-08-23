from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class EMAIndicator:
    """
    Exponential Moving Average (EMA) indicator.
    Conforms to the IndicatorInterface.
    """
    NAME = "EMA"
    VERSION = 1
<<<<<<< Updated upstream
    # Add pane type as overlay per spec
    PANE_TYPE = 'overlay'
    OUTPUTS = ["ema"]
    # Visual metadata for frontend UI
    VISUAL_SCHEMA = {
        "series": {
            "ema": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"},
            }
        }
    }
    VISUAL_DEFAULTS = {
        "series": {
            "ema": {"color": "#1f77b4", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True}
        }
    }
=======
    OUTPUTS = ["ema"]
>>>>>>> Stashed changes
    PARAMS_SCHEMA = {
        "length": {
            "type": "integer",
            "default": 20,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Period",
            "description": "The period for the Exponential Moving Average.",
        },
        "source": {
            "type": "string",
            "default": "close",
            "options": ["open", "high", "low", "close"],
            "ui_only": False,
            "display_name": "Source",
            "description": "The data column to use for EMA calculation.",
        },
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the Exponential Moving Average (EMA).
        """
        length = params["length"]
        source = params["source"]

        if source not in ohlcv.columns:
            logger.error(f"Source column '{source}' not found in DataFrame for EMA calculation.")
            return {"ema": pd.Series(index=ohlcv.index, dtype=float)}

        # Ensure the source column is numeric
        source_series = pd.to_numeric(ohlcv[source], errors='coerce')

        if len(ohlcv) < length:
            logger.warning(f"Not enough data ({len(ohlcv)} bars) for EMA({length}) calculation. Needs at least {length} bars.")
            return {"ema": pd.Series(index=ohlcv.index, dtype=float)}

        try:
            ema_series = ta.ema(close=source_series, length=length)
            if ema_series is None:
                raise ValueError("pandas_ta.ema returned None")
        except Exception as e:
            logger.error(f"Error calculating EMA({length}) from source '{source}': {e}", exc_info=True)
            return {"ema": pd.Series(index=ohlcv.index, dtype=float)}

        return {"ema": ema_series}

# This is a static check to ensure the class adheres to the protocol.
# It's not required for runtime, but good for development.
_t: IndicatorInterface = EMAIndicator()
