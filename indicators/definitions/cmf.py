from typing import Dict
import pandas as pd
import logging

from core.interfaces import IndicatorInterface

logger = logging.getLogger(__name__)

class CMFIndicator:
    """
    Chaikin Money Flow (CMF) Indicator.
    Measures the amount of Money Flow Volume over a specific period.
    Conforms to the IndicatorInterface.
    """
    NAME = "CMF"
    VERSION = 1
    PANE_TYPE = 'pane'
    OUTPUTS = ["cmf"]
    PARAMS_SCHEMA = {
        "length": {
            "type": "integer",
            "default": 20,
            "min": 1,
            "max": 200,
            "ui_only": False,
            "display_name": "Length",
            "description": "Number of periods to use for CMF calculation.",
        }
    }

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        """
        Calculates the Chaikin Money Flow (CMF).
        """
        length = params["length"]

        required_columns = ['high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in ohlcv.columns:
                logger.error(f"Required column '{col}' not found in DataFrame for CMF calculation.")
                return {"cmf": pd.Series(index=ohlcv.index, dtype=float)}

        if len(ohlcv) < length:
            logger.warning(f"Not enough data ({len(ohlcv)} bars) for CMF({length}) calculation. Needs at least {length} bars.")
            return {"cmf": pd.Series(index=ohlcv.index, dtype=float)}

        # Calculate Money Flow Multiplier (MFM)
        high_low_diff = ohlcv['high'] - ohlcv['low']
        mfm = ((ohlcv['close'] - ohlcv['low']) - (ohlcv['high'] - ohlcv['close'])) / high_low_diff
        mfm = mfm.fillna(0)

        # Calculate Money Flow Volume (MFV)
        mfv = mfm * ohlcv['volume']

        # Calculate CMF
        sum_mfv = mfv.rolling(window=length).sum()
        sum_volume = ohlcv['volume'].rolling(window=length).sum()

        cmf = sum_mfv / sum_volume
        cmf = cmf.fillna(0)

        return {"cmf": cmf}

# Static check for protocol adherence
_t: IndicatorInterface = CMFIndicator()
