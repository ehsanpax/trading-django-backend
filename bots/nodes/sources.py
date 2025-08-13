from core.interfaces import IndicatorInterface
import pandas as pd
from typing import Dict

class Price(IndicatorInterface):
    """
    A special indicator that provides access to the raw OHLCV data.
    """
    NAME = "price"
    VERSION = 1
    PARAMS_SCHEMA = {
        "source": {
            "type": "string",
            "enum": ["open", "high", "low", "close", "volume", "tick"],
            "default": "close",
            "display_name": "Source",
            "description": "The price data to use (e.g., close, high).",
        }
    }
    OUTPUTS = ["default"]

    def compute(self, ohlcv: pd.DataFrame, params: Dict) -> Dict[str, pd.Series]:
        source = params.get("source", "close")
        if source == "tick":
            # The backtest engine will need to provide the 'tick' column.
            if "tick" not in ohlcv.columns:
                raise ValueError("Tick data not available in the provided ohlcv data.")
            return {"default": ohlcv["tick"]}
        
        if source not in ohlcv.columns:
            raise ValueError(f"Invalid source '{source}'. Available sources are {list(ohlcv.columns)}")
        return {"default": ohlcv[source]}
