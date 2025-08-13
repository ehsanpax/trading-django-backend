from typing import Dict
import pandas as pd
import pandas_ta as ta
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class ATRIndicator:
    """
    Average True Range (ATR) indicator.
    Conforms to the IndicatorInterface.
    """
    NAME = "ATR"
    VERSION = 1
    PANE_TYPE = 'pane'
    SCALE_TYPE = 'linear'
    OUTPUTS = ["atr"]
    PARAMS_SCHEMA = {
        "length": {
            "type": "integer",
            "default": 14,
            "min": 1,
            "max": 100,
            "ui_only": False,
            "display_name": "Period",
            "description": "The period for the Average True Range calculation.",
        }
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the Average True Range (ATR).
        """
        length = params["length"]

        required_ohlcv = ["high", "low", "close"]
        for col in required_ohlcv:
            if col not in ohlcv.columns:
                logger.error(f"Missing required column '{col}' for ATR calculation.")
                return {"atr": pd.Series(index=ohlcv.index, dtype=float)}
            ohlcv[col] = pd.to_numeric(ohlcv[col], errors='coerce')

        if len(ohlcv) < length:
            logger.warning(f"Not enough data ({len(ohlcv)} bars) for ATR({length}) calculation. Needs at least {length} bars.")
            return {"atr": pd.Series(index=ohlcv.index, dtype=float)}

        try:
            atr_series = ta.atr(high=ohlcv['high'], low=ohlcv['low'], close=ohlcv['close'], length=length)
            if atr_series is None:
                raise ValueError("pandas_ta.atr returned None")
        except Exception as e:
            logger.error(f"Error calculating ATR({length}): {e}", exc_info=True)
            return {"atr": pd.Series(index=ohlcv.index, dtype=float)}

        return {"atr": atr_series}

# Static check for protocol adherence
_t: IndicatorInterface = ATRIndicator()
