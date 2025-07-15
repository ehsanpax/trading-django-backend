from __future__ import annotations

"""
EMA Crossover Strategy v1 (ema_crossover_v1.py)
-------------------------------------------------
A simple EMA crossover strategy.
- Long entry: Short EMA crosses above Long EMA.
- Short entry: Short EMA crosses below Long EMA.
- Stop Loss: ATR-based (e.g., 2 * ATR)
- Take Profit: ATR-based (e.g., 3 * ATR)
"""

from dataclasses import dataclass, field, fields as dataclass_fields
from typing import Literal, Optional, Dict, Any, List
import logging
import io

import numpy as np
import pandas as pd
import pandas_ta as ta

from bots.base import BaseStrategy, BotParameter
from bots.registry import register_strategy, get_indicator_class

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Strategy Class
# ──────────────────────────────────────────────────────────────────────────────

class EMACrossoverV1(BaseStrategy):
    NAME = "ema_crossover_v1"
    DISPLAY_NAME = "EMA Crossover Strategy v1"
    PARAMETERS = [
        BotParameter(
            name="ema_short_period",
            parameter_type="int",
            display_name="Short EMA Period",
            description="Period for the shorter Exponential Moving Average.",
            default_value=21,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="ema_long_period",
            parameter_type="int",
            display_name="Long EMA Period",
            description="Period for the longer Exponential Moving Average.",
            default_value=50,
            min_value=1,
            max_value=200,
            step=1
        ),
        BotParameter(
            name="atr_length",
            parameter_type="int",
            display_name="ATR Length",
            description="Period for the Average True Range (ATR) calculation.",
            default_value=14,
            min_value=1,
            max_value=100,
            step=1
        ),
        BotParameter(
            name="atr_sl_multiple",
            parameter_type="float",
            display_name="ATR Stop Loss Multiple",
            description="Multiplier for ATR to determine Stop Loss distance.",
            default_value=2.0,
            min_value=0.1,
            max_value=10.0,
            step=0.1
        ),
        BotParameter(
            name="atr_tp_multiple",
            parameter_type="float",
            display_name="ATR Take Profit Multiple",
            description="Multiplier for ATR to determine Take Profit distance.",
            default_value=3.0,
            min_value=0.1,
            max_value=10.0,
            step=0.1
        ),
        BotParameter(
            name="risk_per_trade_percent",
            parameter_type="float",
            display_name="Risk Per Trade (%)",
            description="Percentage of account balance to risk per trade.",
            default_value=0.01,
            min_value=0.001,
            max_value=0.1,
            step=0.001
        ),
    ]
    REQUIRED_INDICATORS = [
        {"name": "EMA", "params": {"length": "ema_short_period", "source": "close"}},
        {"name": "EMA", "params": {"length": "ema_long_period", "source": "close"}},
        {"name": "ATR", "params": {"length": "atr_length"}},
    ]

    def __init__(self, instrument_symbol: str, account_id: str, instrument_spec: Any, strategy_params: Dict[str, Any], indicator_params: Dict[str, Any], risk_settings: Dict[str, Any]):
        super().__init__(instrument_symbol, account_id, instrument_spec, strategy_params, indicator_params, risk_settings)
        
        # Access strategy parameters directly from self.strategy_params
        self.ema_short_period = self.strategy_params.get("ema_short_period", self._get_default_param("ema_short_period"))
        self.ema_long_period = self.strategy_params.get("ema_long_period", self._get_default_param("ema_long_period"))
        self.atr_length = self.strategy_params.get("atr_length", self._get_default_param("atr_length"))
        self.atr_sl_multiple = self.strategy_params.get("atr_sl_multiple", self._get_default_param("atr_sl_multiple"))
        self.atr_tp_multiple = self.strategy_params.get("atr_tp_multiple", self._get_default_param("atr_tp_multiple"))
        self.risk_per_trade_percent = self.strategy_params.get("risk_per_trade_percent", self._get_default_param("risk_per_trade_percent"))

        self.tick_size: float = 0.00001 
        self.tick_value: float = 10.0 
        self.contract_size: float = 100000.0
        self.price_digits: int = 5
        self.standard_pip_size_for_buffer: float = 0.0001

        if self.instrument_spec:
            self.tick_size = float(self.instrument_spec.tick_size) if self.instrument_spec.tick_size is not None else self.tick_size
            self.tick_value = float(self.instrument_spec.tick_value) if self.instrument_spec.tick_value is not None else self.tick_value
            self.contract_size = float(self.instrument_spec.contract_size) if self.instrument_spec.contract_size is not None else self.contract_size
            self.price_digits = int(self.instrument_spec.digits) if self.instrument_spec.digits is not None else self.price_digits
            if "JPY" in (self.instrument_symbol or "").upper():
                self.standard_pip_size_for_buffer = 0.01
                if self.instrument_spec.digits == 3: self.price_digits = 3
            elif self.instrument_spec.digits is not None:
                self.standard_pip_size_for_buffer = 10**(-self.instrument_spec.digits +1) if self.instrument_spec.digits > 1 else 0.01
        elif "JPY" in (self.instrument_symbol or "").upper():
            self.tick_size = 0.01
            self.standard_pip_size_for_buffer = 0.01
            self.price_digits = 3

        logger.info(f"EMA Crossover Strategy (class {self.NAME}) initialized for {self.instrument_symbol}. Params: {self.strategy_params}")
        logger.info(f"Instrument Spec derived: tick_size={self.tick_size}, contract_size={self.contract_size}, digits={self.price_digits}")

    def _get_default_param(self, param_name: str) -> Any:
        for param_def in self.PARAMETERS:
            if param_def.name == param_name:
                return param_def.default_value
        return None

    def get_min_bars_needed(self, buffer_bars: int = 10) -> int:
        """Calculates the minimum number of bars required for the strategy."""
        # Max of longest EMA and ATR period, plus 2 for crossover logic, plus buffer
        max_indicator_history = 0
        for req_ind in self.REQUIRED_INDICATORS:
            indicator_class = get_indicator_class(req_ind["name"])
            if indicator_class:
                # Resolve dynamic parameters from strategy_params
                resolved_params = {k: self.strategy_params.get(v, v) if isinstance(v, str) and v in self.strategy_params else v for k, v in req_ind["params"].items()}
                max_indicator_history = max(max_indicator_history, indicator_class().required_history(**resolved_params))
        
        return max(max_indicator_history, self.ema_long_period, self.atr_length) + 2 + buffer_bars

    def _ensure_indicators(self, df_input: pd.DataFrame) -> pd.DataFrame:
        df = df_input.copy()

        required_ohlcv = ["open", "high", "low", "close"]
        for col in required_ohlcv:
            if col not in df.columns:
                logger.error(f"Missing required column '{col}' for indicator calculation. Symbol: {self.instrument_symbol}")
                df[col] = np.nan
            else:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        try:
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, utc=True)
            if isinstance(df.index, pd.Timestamp):
                original_index_name = df.index.name if hasattr(df.index, 'name') else None
                df.index = pd.DatetimeIndex([df.index], name=original_index_name)
            if not df.index.is_monotonic_increasing:
                df = df.sort_index()
        except Exception as e_idx:
            logger.error(f"Error refreshing or validating index: {e_idx}", exc_info=True)
            return df # Return df as is, further checks will handle NaNs

        min_rows_for_ta = self.get_min_bars_needed(buffer_bars=0) # Use strategy's method
        if len(df.index) < min_rows_for_ta :
            timestamp_info = df.index[-1] if not df.empty and isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0 else 'N/A'
            logger.warning(f"DataFrame for {self.instrument_symbol} has {len(df.index)} row(s) at {timestamp_info}, needs {min_rows_for_ta}. Skipping TA.")
            return df
        
        # Calculate indicators using the new BaseIndicator structure
        for req_ind in self.REQUIRED_INDICATORS:
            indicator_name = req_ind["name"]
            indicator_class = get_indicator_class(indicator_name)
            if indicator_class:
                # Resolve dynamic parameters from strategy_params
                resolved_params = {k: self.strategy_params.get(v, v) if isinstance(v, str) and v in self.strategy_params else v for k, v in req_ind["params"].items()}
                try:
                    indicator_instance = indicator_class()
                    df = indicator_instance.calculate(df, **resolved_params)
                except Exception as e:
                    logger.error(f"Error calculating indicator {indicator_name} for {self.instrument_symbol}: {e}", exc_info=True)
            else:
                logger.warning(f"Indicator '{indicator_name}' not found in registry.")
            
        return df

    def get_indicator_column_names(self) -> List[str]:
        """
        Returns a list of column names that this strategy adds as indicators
        to the DataFrame. This is used by the backtesting engine to know
        which columns to store as indicator data.
        """
        # This method needs to be dynamic based on the actual indicator implementations
        # For now, hardcode for EMA Crossover, but this should be derived from BaseIndicator.calculate
        return [
            f"EMA_{self.ema_short_period}",
            f"EMA_{self.ema_long_period}",
            f"ATRr_{self.atr_length}"
        ]

    def _calculate_lot_size(self, account_equity: float, sl_pips: float) -> Optional[float]:
        if account_equity <= 0 or self.risk_per_trade_percent <= 0 or sl_pips <= 0:
            return None
        
        risk_amount_per_trade = account_equity * self.risk_per_trade_percent
        price_risk_per_unit = sl_pips 
        if price_risk_per_unit < self.tick_size:
             logger.warning(f"[{self.instrument_symbol}] Price risk ({price_risk_per_unit}) is smaller than tick size ({self.tick_size}). Cannot calculate lot size.")
             return None

        fixed_lot_size = self.risk_settings.get("fixed_lot_size")
        if fixed_lot_size: return float(fixed_lot_size)

        if self.tick_size > 0 and self.tick_value > 0: 
            cash_risk_per_lot = (price_risk_per_unit / self.tick_size) * self.tick_value
            if cash_risk_per_lot > 0:
                calculated_lot_size = risk_amount_per_trade / cash_risk_per_lot
                
                if self.instrument_spec and self.instrument_spec.volume_step is not None and self.instrument_spec.volume_step > 0:
                    vol_step = float(self.instrument_spec.volume_step)
                    calculated_lot_size = np.floor(calculated_lot_size / vol_step) * vol_step
                
                min_vol = float(self.instrument_spec.min_volume) if self.instrument_spec and self.instrument_spec.min_volume is not None else 0.01
                max_vol = float(self.instrument_spec.max_volume) if self.instrument_spec and self.instrument_spec.max_volume is not None else 1000.0
                
                calculated_lot_size = max(min_vol, min(calculated_lot_size, max_vol))
                
                if calculated_lot_size < min_vol:
                    logger.warning(f"[{self.instrument_symbol}] Calculated lot size {calculated_lot_size} is below min_volume {min_vol}. No trade.")
                    return None
                return round(calculated_lot_size, 2)
        
        logger.warning(f"[{self.instrument_symbol}] Lot size calculation failed. Using 0.01 as fallback.")
        return 0.01

    def _place_trade_signal(self, current_price: float, direction: Literal["BUY", "SELL"], 
                              sl_price: float, tp_price: float, account_equity: float,
                              atr_val: float, timestamp: pd.Timestamp) -> Optional[Dict[str, Any]]:

        sl_distance = abs(current_price - sl_price)
        lot_size = self._calculate_lot_size(account_equity, sl_distance)

        if not lot_size or lot_size <= 0:
            logger.warning(f"[{self.instrument_symbol}] Invalid lot size: {lot_size} for SL distance {sl_distance}. No trade signal.")
            return None

        trade_details = {
            "symbol": self.instrument_symbol, "direction": direction, "order_type": "MARKET",
            "volume": lot_size, "price": current_price,
            "stop_loss": round(sl_price, self.price_digits),
            "take_profit": round(tp_price, self.price_digits),
            "comment": f"EMACrossoverV1 {self.instrument_symbol} {direction} @ {timestamp}", # Original name for comment
            "strategy_info": {
                "ema_short": self.ema_short_period,
                "ema_long": self.ema_long_period,
                "atr_period": self.atr_length,
                "atr_value_at_signal": round(atr_val, self.price_digits),
                "sl_atr_multiple": self.atr_sl_multiple,
                "tp_atr_multiple": self.atr_tp_multiple,
            }
        }
        logger.info(f"[{self.instrument_symbol}@{timestamp}] Signaling {direction} trade: SL {sl_price:.{self.price_digits}f}, TP {tp_price:.{self.price_digits}f}, Vol {lot_size}")
        return {'action': 'OPEN_TRADE', 'details': trade_details}

    def run_tick(self, df_current_window: pd.DataFrame, account_equity: float) -> List[Dict[str, Any]]:
        actions = []
        
        required_bars = self.get_min_bars_needed(buffer_bars=0)
        if len(df_current_window) < required_bars:
            return actions

        df = self._ensure_indicators(df_current_window)
        
        ema_short_col = f"EMA_{self.ema_short_period}"
        ema_long_col = f"EMA_{self.ema_long_period}"
        atr_col = f"ATRr_{self.atr_length}"

        if not all(col in df.columns for col in [ema_short_col, ema_long_col, atr_col, "close", "open"]):
            logger.debug(f"[{self.instrument_symbol}] Missing required columns after indicator calculation. Columns: {df.columns}")
            return actions
        
        if df[[ema_short_col, ema_long_col, atr_col, "close"]].iloc[-2:].isnull().any().any():
            logger.debug(f"[{self.instrument_symbol}] NaN values in recent indicator/price data. Skipping tick.")
            return actions

        current_bar = df.iloc[-1]
        prev_bar = df.iloc[-2]

        current_price = current_bar["close"]
        current_atr = current_bar[atr_col]
        
        if pd.isna(current_atr) or current_atr == 0:
            logger.debug(f"[{self.instrument_symbol}] Invalid ATR ({current_atr}) for trade signal. Skipping tick.")
            return actions

        if prev_bar[ema_short_col] < prev_bar[ema_long_col] and \
           current_bar[ema_short_col] > current_bar[ema_long_col]:
            sl_price = current_price - (current_atr * self.atr_sl_multiple)
            tp_price = current_price + (current_atr * self.atr_tp_multiple)
            signal = self._place_trade_signal(current_price, "BUY", sl_price, tp_price, account_equity, current_atr, current_bar.name)
            if signal: actions.append(signal)

        elif prev_bar[ema_short_col] > prev_bar[ema_long_col] and \
             current_bar[ema_short_col] < current_bar[ema_long_col]:
            sl_price = current_price + (current_atr * self.atr_sl_multiple)
            tp_price = current_price - (current_atr * self.atr_tp_multiple)
            signal = self._place_trade_signal(current_price, "SELL", sl_price, tp_price, account_equity, current_atr, current_bar.name)
            if signal: actions.append(signal)
            
        return actions

# Register the strategy
register_strategy(EMACrossoverV1.NAME, EMACrossoverV1)

if __name__ == "__main__":
    try:
        import yfinance as yf
        logger.setLevel(logging.DEBUG) 
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        symbol_yf = "EURUSD=X"; symbol_platform = "EURUSD"
        data_yf = yf.download(symbol_yf, interval="15m", period="120d")
        if data_yf.empty:
            print(f"No data for {symbol_yf}")
        else:
            data_yf.rename(columns=str.lower, inplace=True)
            if 'Open' in data_yf.columns and 'open' not in data_yf.columns:
                 data_yf.rename(columns={'Open':'open'}, inplace=True)

            print(f"Data for {symbol_yf}: {len(data_yf)} bars from {data_yf.index.min()} to {data_yf.index.max()}")
            
            class MockInstrumentSpec:
                def __init__(self, symbol):
                    self.symbol = symbol
                    self.tick_size = 0.00001 if "JPY" not in symbol.upper() else 0.001
                    self.tick_value = 1.0 if "JPY" not in symbol.upper() else 1000.0 
                    self.contract_size = 100000.0
                    self.digits = 5 if "JPY" not in symbol.upper() else 3
                    self.min_volume = 0.01
                    self.max_volume = 100.0
                    self.volume_step = 0.01

            mock_spec = MockInstrumentSpec(symbol_platform)
            
            # Example of how to instantiate with new parameters
            # For testing, we need to mock get_indicator_class
            class MockEMAIndicator:
                NAME = "EMA"
                def calculate(self, df, length, source):
                    df.ta.ema(length=length, append=True, close=df[source])
                    return df
                def required_history(self, length):
                    return length + 1

            class MockATRIndicator:
                NAME = "ATR"
                def calculate(self, df, length):
                    df.ta.atr(length=length, append=True)
                    return df
                def required_history(self, length):
                    return length + 1

            # Temporarily register mock indicators for testing purposes
            from bots.registry import INDICATOR_REGISTRY
            INDICATOR_REGISTRY["EMA"] = MockEMAIndicator
            INDICATOR_REGISTRY["ATR"] = MockATRIndicator

            bot_params = {
                "ema_short_period": 21,
                "ema_long_period": 50,
                "atr_length": 14,
                "atr_sl_multiple": 2.0,
                "atr_tp_multiple": 3.0,
                "risk_per_trade_percent": 0.01,
            }
            bot = EMACrossoverV1( 
                instrument_symbol=symbol_platform, 
                instrument_spec=mock_spec,
                strategy_params=bot_params,
                indicator_params={}, # No specific indicator params passed to strategy init
                risk_settings={}
            )
            
            min_data_needed = bot.get_min_bars_needed(buffer_bars=20)

            for i in range(min_data_needed, len(data_yf)):
                current_window_df = data_yf.iloc[i - min_data_needed : i+1]
                if current_window_df.empty:
                    continue
                
                actions = bot.run_tick(df_current_window=current_window_df, account_equity=10000.0)
                if actions:
                    print(f"Time: {current_window_df.index[-1]}, Actions: {actions}")
            print("Example run finished.")
    except ImportError:
        print("yfinance or pandas_ta not installed.")
    except Exception as e:
        print(f"Error in example: {e}")
        import traceback
        traceback.print_exc()
