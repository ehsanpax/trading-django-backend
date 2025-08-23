from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class StochasticRSIIndicator:
    """
    Stochastic RSI Indicator.
    Conforms to the IndicatorInterface.
    """
    NAME = "StochasticRSI"
    VERSION = 1
    PANE_TYPE = 'pane'
    OUTPUTS = ["stoch_rsi_k", "stoch_rsi_d"]
<<<<<<< Updated upstream
    # Visual metadata
    VISUAL_SCHEMA = {
        "series": {
            "stoch_rsi_k": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"}
            },
            "stoch_rsi_d": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"}
            }
        },
        "guides": {
            "upper": {"value": {"type": "number"}, "color": {"type": "string"}, "visible": {"type": "boolean"}},
            "lower": {"value": {"type": "number"}, "color": {"type": "string"}, "visible": {"type": "boolean"}}
        }
    }
    VISUAL_DEFAULTS = {
        "series": {
            "stoch_rsi_k": {"color": "#1f77b4", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True},
            "stoch_rsi_d": {"color": "#d62728", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True}
        },
        "guides": {
            "upper": {"value": 80, "color": "#808080", "visible": True},
            "lower": {"value": 20, "color": "#808080", "visible": True}
        }
    }
=======
>>>>>>> Stashed changes
    PARAMS_SCHEMA = {
        "rsi_length": {
            "type": "integer",
            "default": 14,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "RSI Length",
        },
        "stoch_length": {
            "type": "integer",
            "default": 14,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Stochastic Length",
        },
        "k_period": {
            "type": "integer",
            "default": 3,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "%K Period",
        },
        "d_period": {
            "type": "integer",
            "default": 3,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "%D Period",
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
        Calculates the Stochastic RSI (%K and %D lines).
        """
        rsi_length = params["rsi_length"]
        stoch_length = params["stoch_length"]
        k = params["k_period"]
        d = params["d_period"]
        source = params["source"]

        if source not in ohlcv.columns:
            logger.error(f"Source column '{source}' not found in DataFrame for Stochastic RSI calculation.")
            return {}

        try:
            stoch_rsi = ta.stochrsi(close=ohlcv[source], rsi_length=rsi_length, length=stoch_length, k=k, d=d)
            if stoch_rsi is None or stoch_rsi.empty:
                raise ValueError("pandas_ta.stochrsi returned None or empty DataFrame")

            output = {
                "stoch_rsi_k": stoch_rsi[f'STOCHRSIk_{rsi_length}_{stoch_length}_{k}_{d}'],
                "stoch_rsi_d": stoch_rsi[f'STOCHRSId_{rsi_length}_{stoch_length}_{k}_{d}']
            }
        except Exception as e:
            logger.error(f"Error calculating Stochastic RSI: {e}", exc_info=True)
            return {}

        return output

# Static check for protocol adherence
_t: IndicatorInterface = StochasticRSIIndicator()
