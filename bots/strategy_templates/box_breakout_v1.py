from __future__ import annotations

"""
Box Breakout Divergence Bot v1 (box_breakout_v1.py)
---------------------------------------------------
A modular trading bot that looks for a tight consolidation ("box") followed by
bullish MACD + CMF divergence and goes long on a confirmed breakout.
Adapted for the trading_platform bots app.
"""

from dataclasses import dataclass, fields as dataclass_fields
from typing import Literal, Optional, Dict, Any, List
import logging
from decimal import Decimal # For precise financial calculations
import io # For logging DataFrame info

import numpy as np
import pandas as pd
import pandas_ta as ta # pandas-ta should be in requirements.txt

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Parameters
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BoxBreakoutParams:
    # range detection
    lookback: int = 20               # bars to define the box
    max_atr_multiple: float = 2    # box height must be < 0.5 × ATR
    # divergence detection
    slope_window: int = 5            # bars used to measure indicator slope
    # entry & risk
    risk_per_trade_percent: float = 0.005 # 0.5% of balance
    tp_multiple: float = 2.0         # TP distance = multiple × box height
    sl_buffer_pips: float = 1.0      # extra pips under box_low for SL
    require_retest: bool = False     # wait for retest before entry
    
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    cmf_length: int = 20
    atr_length: int = 14

    @classmethod
    def from_dict(cls, params_dict: Dict[str, Any]) -> BoxBreakoutParams:
        known_fields = {f.name for f in dataclass_fields(cls)}
        filtered_params = {k: v for k, v in params_dict.items() if k in known_fields}
        return cls(**filtered_params)

# ──────────────────────────────────────────────────────────────────────────────
# Strategy Class
# ──────────────────────────────────────────────────────────────────────────────

class BoxBreakoutV1Strategy:
    ParamsDataclass = BoxBreakoutParams # Convention for parameter discovery
    DEFAULT_PARAMS = {
        "lookback": 20, "max_atr_multiple": 0.5, "slope_window": 5,
        "risk_per_trade_percent": 0.005, "tp_multiple": 2.0, "sl_buffer_pips": 1.0,
        "require_retest": False, "macd_fast": 12, "macd_slow": 26,
        "macd_signal": 9, "cmf_length": 20, "atr_length": 14,
    }

    def __init__(self, params: Optional[Dict[str, Any]] = None, 
                 risk_settings: Optional[Dict[str, Any]] = None,
                 instrument_symbol: Optional[str] = None,
                 account_id: Optional[str] = None,
                 instrument_spec = None, # trading.models.InstrumentSpecification instance
                 pip_value: float = 0.0001 # Fallback if instrument_spec not provided
                ):
        
        actual_params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.p = BoxBreakoutParams.from_dict(actual_params)
        
        self.risk_settings = risk_settings or {}
        self.instrument_symbol = instrument_symbol
        self.account_id = account_id
        
        self.instrument_spec = instrument_spec
        self.tick_size: float = 0.00001 # Default
        self.tick_value: float = 10.0 # Default for 1 lot USD account, non-JPY
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
                if self.instrument_spec.digits == 3: self.price_digits = 3 # Common for JPY
            elif self.instrument_spec.digits is not None:
                 # For 2/3 decimal (JPY like) or 4/5 decimal (most others)
                self.standard_pip_size_for_buffer = 10**(-self.instrument_spec.digits +1) if self.instrument_spec.digits > 1 else 0.01
        elif "JPY" in (self.instrument_symbol or "").upper(): # Fallback if no spec
            self.tick_size = 0.01
            self.standard_pip_size_for_buffer = 0.01
            self.price_digits = 3


        logger.info(f"BoxBreakoutV1Strategy initialized for {self.instrument_symbol}. Params: {self.p}")
        logger.info(f"Instrument Spec derived: tick_size={self.tick_size}, tick_value={self.tick_value}, contract_size={self.contract_size}, digits={self.price_digits}, standard_pip_for_buffer={self.standard_pip_size_for_buffer}")
        logger.info(f"Risk settings for backtest (if any): {self.risk_settings}")

        self._box_high: Optional[float] = None
        self._box_low: Optional[float] = None
        self._setup_active = False
        self._waiting_for_retest = False

    def get_min_bars_needed(self, buffer_bars: int = 0) -> int:
        """Calculates the minimum number of bars required by the strategy for its indicators and lookbacks."""
        # Core requirement: sum of lookback for box, slope window for divergence, ATR length, 
        # plus a small internal buffer (e.g., 5 bars) for calculations.
        # The run_tick method uses: self.p.lookback + self.p.slope_window + self.p.atr_length + 5
        core_requirement = self.p.lookback + self.p.slope_window + self.p.atr_length + 5
        return core_requirement + buffer_bars

    def _ensure_indicators(self, df_input: pd.DataFrame) -> pd.DataFrame:
        df = df_input.copy()

        required_ohlcv = ["high", "low", "close", "volume"]
        for col in required_ohlcv:
            if col not in df.columns:
                logger.error(f"Missing required column '{col}' for indicator calculation. Symbol: {self.instrument_symbol}")
                df[col] = np.nan
            else:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        macd_hist_col = f"MACDh_{self.p.macd_fast}_{self.p.macd_slow}_{self.p.macd_signal}"
        cmf_col = f"CMF_{self.p.cmf_length}"
        atr_col = f"ATRr_{self.p.atr_length}"

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
            df[macd_hist_col] = np.nan
            df[cmf_col] = np.nan
            df[atr_col] = np.nan
            return df

        if len(df.index) < 2:
            timestamp_info = df.index[-1] if not df.empty and isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0 else 'N/A'
            logger.warning(f"DataFrame for {self.instrument_symbol} has {len(df.index)} row(s) at {timestamp_info}, skipping TA.")
            if macd_hist_col not in df.columns: df[macd_hist_col] = np.nan
            if cmf_col not in df.columns: df[cmf_col] = np.nan
            if atr_col not in df.columns: df[atr_col] = np.nan
            return df
        
        try:
            # MACD - Should be working
            if macd_hist_col not in df.columns:
                if len(df) >= self.p.macd_slow + self.p.macd_signal:
                    logger.debug(f"DataFrame before MACD for {self.instrument_symbol} at {df.index[-1]}: Index type: {type(df.index)}, Shape: {df.shape}")
                    df.ta.macd(fast=self.p.macd_fast, slow=self.p.macd_slow, signal=self.p.macd_signal, append=True)
                    if macd_hist_col not in df.columns:
                        df[macd_hist_col] = np.nan
                        logger.warning(f"MACD hist column '{macd_hist_col}' not created by ta.macd.")
                else:
                    df[macd_hist_col] = np.nan
            
            # CMF - Should be working
            if cmf_col not in df.columns:
                if len(df) >= self.p.cmf_length:
                    logger.debug(f"DataFrame before CMF for {self.instrument_symbol} at {df.index[-1]}: Index type: {type(df.index)}, Shape: {df.shape}")
                    df.ta.cmf(length=self.p.cmf_length, append=True)
                    if cmf_col not in df.columns:
                        df[cmf_col] = np.nan
                        logger.warning(f"CMF column '{cmf_col}' not created by ta.cmf.")
                else:
                     df[cmf_col] = np.nan

            # ATR - Testing this now
            if atr_col not in df.columns:
                if len(df) >= self.p.atr_length:
                    #logger.info(f"Attempting ATR calculation for {self.instrument_symbol}...")
                    logger.debug(f"DataFrame before ATR for {self.instrument_symbol} at {df.index[-1]}: Index type: {type(df.index)}, Shape: {df.shape}")
                    buf = io.StringIO()
                    df.info(buf=buf)
                    logger.debug(f"Info before ATR:\n{buf.getvalue()}")
                    logger.debug(f"Head before ATR:\n{df.head().to_string()}")
                    
                    df.ta.atr(length=self.p.atr_length, append=True)
                    if atr_col in df.columns: 
                        df[atr_col] = df[atr_col].bfill().fillna(self.tick_size * 10)
                    else: 
                        df[atr_col] = np.nan
                        logger.warning(f"ATR column '{atr_col}' not created by ta.atr.")
                else: 
                     df[atr_col] = np.nan

        except Exception as e:
            logger.error(f"Error during pandas_ta indicator calculation (ATR focused): {e}", exc_info=True)
            if macd_hist_col not in df.columns: df[macd_hist_col] = np.nan
            if cmf_col not in df.columns: df[cmf_col] = np.nan 
            if atr_col not in df.columns: df[atr_col] = np.nan
            
        return df

    def _slope(self, series: pd.Series) -> float:
        series = series.dropna() 
        if series.empty or len(series) < 2:
            return 0.0
        y = series.values
        x = np.arange(len(y))
        if y.std() == 0:
            return 0.0
        return np.polyfit(x, y, 1)[0]

    def _maybe_start_setup(self, df: pd.DataFrame) -> None:
        if self._setup_active: return
        if len(df) < self.p.lookback: return

        window = df.iloc[-self.p.lookback:]
        box_high = window["high"].max()
        box_low = window["low"].min()
        box_height = box_high - box_low
        
        atr_col = f"ATRr_{self.p.atr_length}" 
        macd_hist_col = f"MACDh_{self.p.macd_fast}_{self.p.macd_slow}_{self.p.macd_signal}"
        cmf_col = f"CMF_{self.p.cmf_length}"

        current_atr = window[atr_col].iloc[-1] if atr_col in window.columns and not window[atr_col].empty else np.nan
        
        if pd.isna(current_atr) or current_atr == 0:
            logger.debug(f"Invalid ATR ({current_atr}) for setup check. Symbol: {self.instrument_symbol}")
            return

        closes_inside = (window["close"] <= box_high) & (window["close"] >= box_low)
        in_box_condition = closes_inside.all() and box_height > self.tick_size and box_height < (self.p.max_atr_multiple * current_atr) 
        if not in_box_condition: return

        if len(window) < self.p.slope_window: return
        
        if not all(col in window.columns for col in [macd_hist_col, cmf_col, "close"]):
            logger.debug(f"Missing indicator columns for divergence check. Columns: {window.columns}. Symbol: {self.instrument_symbol}")
            return

        macd_series = window[macd_hist_col].tail(self.p.slope_window)
        cmf_series = window[cmf_col].tail(self.p.slope_window)
        price_series = window["close"].tail(self.p.slope_window)

        macd_slope = self._slope(macd_series)
        cmf_slope = self._slope(cmf_series)
        price_slope = self._slope(price_series)

        divergence_ok = macd_slope > 0 and cmf_slope > 0 and price_slope <= 0

        if divergence_ok:
            self._setup_active = True
            self._box_high = box_high
            self._box_low = box_low
            self._waiting_for_retest = self.p.require_retest
            logger.info(f"[{self.instrument_symbol}@{df.index[-1]}] Setup ACTIVATED: Box [{self._box_low:.{self.price_digits}f} - {self._box_high:.{self.price_digits}f}], ATR: {current_atr:.{self.price_digits}f}, Div OK.")

    def _calculate_lot_size(self, account_equity: float, sl_price: float, entry_price: float) -> Optional[float]:
        if account_equity <= 0 or self.p.risk_per_trade_percent <= 0: return None
        
        risk_amount_per_trade = account_equity * self.p.risk_per_trade_percent
        price_risk_per_unit = abs(entry_price - sl_price)
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

                logger.info(f"[{self.instrument_symbol}] Calculated lot size: {calculated_lot_size:.2f} for risk ${risk_amount_per_trade:.2f}, price risk {price_risk_per_unit:.{self.price_digits}f}")
                return round(calculated_lot_size, 2) 

        logger.warning(f"[{self.instrument_symbol}] Lot size calculation failed due to missing spec/values. Using 0.01 as fallback.")
        return 0.01

    def _place_long_trade_signal(self, df: pd.DataFrame, account_equity: float) -> Optional[Dict[str, Any]]:
        if self._box_high is None or self._box_low is None: return None
        box_height = self._box_high - self._box_low
        sl_adjustment = self.p.sl_buffer_pips * self.standard_pip_size_for_buffer
        
        sl_price = self._box_low - sl_adjustment
        tp_price = self._box_high + (box_height * self.p.tp_multiple)
        entry_price = df.iloc[-1]["close"]

        lot_size = self._calculate_lot_size(account_equity, sl_price, entry_price)
        if not lot_size or lot_size <= 0:
            logger.warning(f"[{self.instrument_symbol}] Invalid lot size: {lot_size}. No trade signal.")
            return None
        
        atr_col = f"ATRr_{self.p.atr_length}" 
        atr_at_setup_val = np.nan
        if atr_col in df.columns and not df[atr_col].iloc[-self.p.lookback:].empty:
             atr_at_setup_val = round(df[atr_col].iloc[-self.p.lookback:].mean(), self.price_digits)


        trade_details = {
            "symbol": self.instrument_symbol, "direction": "BUY", "order_type": "MARKET",
            "volume": lot_size, "price": entry_price,
            "stop_loss": round(sl_price, self.price_digits),
            "take_profit": round(tp_price, self.price_digits),
            "comment": f"BoxBreakoutV1 {self.instrument_symbol} Long @ {df.index[-1]}",
            "strategy_info": {
                "box_high": round(self._box_high, self.price_digits), 
                "box_low": round(self._box_low, self.price_digits), 
                "box_height": round(box_height, self.price_digits),
                "atr_at_setup": atr_at_setup_val
            }
        }
        logger.info(f"[{self.instrument_symbol}@{df.index[-1]}] Signaling LONG trade: SL {sl_price:.{self.price_digits}f}, TP {tp_price:.{self.price_digits}f}, Vol {lot_size}")
        return {'action': 'OPEN_TRADE', 'details': trade_details}

    def _reset_setup(self):
        self._setup_active = False
        self._box_high = None
        self._box_low = None
        self._waiting_for_retest = False
        logger.debug(f"[{self.instrument_symbol}] Setup RESET.")

    def run_tick(self, df_current_window: pd.DataFrame, account_equity: float) -> List[Dict[str, Any]]:
        actions = []
        required_bars = self.p.lookback + self.p.slope_window + self.p.atr_length + 5 
        if len(df_current_window) < required_bars:
            return actions

        df_with_indicators = self._ensure_indicators(df_current_window)
        
        if not self._setup_active:
            self._maybe_start_setup(df_with_indicators)

        if self._setup_active:
            last_bar = df_with_indicators.iloc[-1]
            sl_adj_for_invalidation = self.p.sl_buffer_pips * self.standard_pip_size_for_buffer
            
            if self._box_low and last_bar["close"] < self._box_low - sl_adj_for_invalidation:
                logger.info(f"[{self.instrument_symbol}@{df_with_indicators.index[-1]}] Setup invalidated. Price closed below box_low. Resetting.")
                self._reset_setup()
                return actions

            breakout_confirmed = last_bar["close"] > self._box_high

            if self.p.require_retest:
                if breakout_confirmed and not self._waiting_for_retest: 
                    self._waiting_for_retest = True
                    logger.info(f"[{self.instrument_symbol}@{df_with_indicators.index[-1]}] Breakout detected above {self._box_high:.{self.price_digits}f}. Waiting for retest.")
                
                if self._waiting_for_retest: 
                    retest_touch_condition = last_bar["low"] <= self._box_high and last_bar["high"] >= self._box_high
                    retest_bounce_entry_condition = last_bar["close"] > self._box_high 
                    
                    if retest_touch_condition and retest_bounce_entry_condition:
                        logger.info(f"[{self.instrument_symbol}@{df_with_indicators.index[-1]}] Retest of {self._box_high:.{self.price_digits}f} and bounce confirmed. Signaling trade.")
                        trade_signal = self._place_long_trade_signal(df_with_indicators, account_equity)
                        if trade_signal: actions.append(trade_signal)
                        self._reset_setup()
                    elif retest_touch_condition:
                        logger.debug(f"[{self.instrument_symbol}@{df_with_indicators.index[-1]}] Retest touch of {self._box_high:.{self.price_digits}f}. Waiting for bounce confirmation.")
            else: 
                if breakout_confirmed:
                    logger.info(f"[{self.instrument_symbol}@{df_with_indicators.index[-1]}] Breakout confirmed (no retest required). Signaling trade.")
                    trade_signal = self._place_long_trade_signal(df_with_indicators, account_equity)
                    if trade_signal: actions.append(trade_signal)
                    self._reset_setup()
        return actions

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
            
            bot = BoxBreakoutV1Strategy(
                params={"risk_per_trade_percent": 0.01, "sl_buffer_pips": 2, "require_retest": True}, 
                instrument_symbol=symbol_platform, 
                instrument_spec=mock_spec
            )
            
            min_data_needed = bot.p.lookback + bot.p.slope_window + bot.p.atr_length + 20 

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
