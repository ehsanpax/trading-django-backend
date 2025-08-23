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
<<<<<<< Updated upstream
    # Visual metadata
    VISUAL_SCHEMA = {
        "series": {
            "plus_di": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"}
            },
            "minus_di": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"}
            },
            "adx": {
                "color": {"type": "string"},
                "lineStyle": {"type": "string", "enum": ["solid", "dashed", "dotted"]},
                "lineWidth": {"type": "integer", "min": 1, "max": 5},
                "plotType": {"type": "string", "enum": ["line"]},
                "visible": {"type": "boolean"}
            }
        }
    }
    VISUAL_DEFAULTS = {
        "series": {
            "plus_di": {"color": "#2ca02c", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True},
            "minus_di": {"color": "#d62728", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True},
            "adx": {"color": "#1f77b4", "lineStyle": "solid", "lineWidth": 1, "plotType": "line", "visible": True}
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
            dmi_df = None
            # Prefer pandas_ta.dmi if available
            if hasattr(ta, 'dmi'):
                try:
                    dmi_df = ta.dmi(high=ohlcv['high'], low=ohlcv['low'], close=ohlcv['close'], length=length)
                except Exception:
                    dmi_df = None
            # Fallback to pandas_ta.adx (commonly available across versions)
            if dmi_df is None or getattr(dmi_df, 'empty', True):
                if hasattr(ta, 'adx'):
                    dmi_df = ta.adx(high=ohlcv['high'], low=ohlcv['low'], close=ohlcv['close'], length=length)

            if dmi_df is None or dmi_df.empty:
                raise ValueError("pandas_ta.dmi/adx returned None or empty DataFrame")
            
            output = {
                "plus_di": dmi_df[f'DMP_{length}'],
                "minus_di": dmi_df[f'DMN_{length}'],
                "adx": dmi_df[f'ADX_{length}']
            }
        except Exception as e:
            logger.error(f"Error calculating DMI({length}): {e}", exc_info=True)
            return {}

        return output

# Static check for protocol adherence
_t: IndicatorInterface = DMIIndicator()
