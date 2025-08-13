from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class SMIIndicator:
    """
    Stochastic Momentum Index (SMI) Indicator.
    Conforms to the IndicatorInterface.
    """
    NAME = "SMI"
    VERSION = 1
    PANE_TYPE = 'pane'
    OUTPUTS = ["smi", "signal"]
    PARAMS_SCHEMA = {
        "k_length": {
            "type": "integer",
            "default": 10,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "%K Length",
        },
        "d_length": {
            "type": "integer",
            "default": 3,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "%D Length",
        },
        "smoothing_length": {
            "type": "integer",
            "default": 3,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Smoothing Length",
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
        Calculates the Stochastic Momentum Index (SMI).
        """
        k = params["k_length"]
        d = params["d_length"]
        s = params["smoothing_length"]
        source = params["source"]

        required_columns = [source, 'high', 'low']
        for col in required_columns:
            if col not in ohlcv.columns:
                logger.error(f"Required column '{col}' not found in DataFrame for SMI calculation.")
                return {}

        try:
            smi = ta.smi(close=ohlcv[source], high=ohlcv['high'], low=ohlcv['low'], k=k, d=d, s=s)
            if smi is None or smi.empty:
                raise ValueError("pandas_ta.smi returned None or empty DataFrame")

            output = {
                "smi": smi[f'SMI_{k}_{d}_{s}'],
                "signal": smi[f'SMIs_{k}_{d}_{s}']
            }
        except Exception as e:
            logger.error(f"Error calculating SMI: {e}", exc_info=True)
            return {}

        return output

# Static check for protocol adherence
_t: IndicatorInterface = SMIIndicator()
