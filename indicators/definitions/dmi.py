from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class DMIIndicator:
    """
    Directional Movement Index (DMI) Indicator.
    Conforms to the IndicatorInterface.
    """
    NAME = "DMI"
    VERSION = 1
    PANE_TYPE = 'pane'
    OUTPUTS = ["plus_di", "minus_di", "adx"]
    PARAMS_SCHEMA = {
        "length": {
            "type": "integer",
            "default": 14,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Length",
            "description": "Number of periods to use for DI and ADX calculation.",
        }
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the Directional Movement Index (+DI, -DI, ADX).
        """
        length = params["length"]

        required_columns = ['high', 'low', 'close']
        for col in required_columns:
            if col not in ohlcv.columns:
                logger.error(f"Required column '{col}' not found in DataFrame for DMI calculation.")
                return {}

        if len(ohlcv) < length + 1:
            logger.warning(f"Not enough data ({len(ohlcv)} bars) for DMI({length}) calculation.")
            return {}

        try:
            dmi = ta.dmi(high=ohlcv['high'], low=ohlcv['low'], close=ohlcv['close'], length=length)
            if dmi is None or dmi.empty:
                raise ValueError("pandas_ta.dmi returned None or empty DataFrame")
            
            output = {
                "plus_di": dmi[f'DMP_{length}'],
                "minus_di": dmi[f'DMN_{length}'],
                "adx": dmi[f'ADX_{length}']
            }
        except Exception as e:
            logger.error(f"Error calculating DMI({length}): {e}", exc_info=True)
            return {}

        return output

# Static check for protocol adherence
_t: IndicatorInterface = DMIIndicator()
