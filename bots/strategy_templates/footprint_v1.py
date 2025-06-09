"""
Footprint Strategy v1 (footprint_v1.py)
Based on "Footprint Strategy Logic Deep Dive (1).pdf" and "strategy engine.docx".
"""
import logging
from decimal import Decimal

# Configure logging for the strategy
logger = logging.getLogger(__name__)

class FootprintV1Strategy:
    """
    Encapsulates the Footprint v1 trading strategy logic.
    """

    # Default parameters as per "Footprint Strategy Logic Deep Dive (1).pdf"
    DEFAULT_PARAMS = {
        "PIVOT_RANGE": 3,
        "BOS_BUFFER": 0.001,  # 0.1%
        "IMBALANCE_FACTOR": 3,
        "ATR_H1_LOOKBACK": 14,
        "SL_ATR_MULT": 0.25,
        "MAX_CONSEC_LOSS": 4,
        # Parameters from "strategy engine.docx" (Section 5: Strategy Logic)
        "VOL_GATE_ATR_H1_LOOKBACK_DAYS": 90, # For 90-day median ATR
        "VOL_GATE_ATR_MULT": 0.75,
        "ORDER_FLOW_CONFIRM_DELTAS": 2, # Two consecutive 1-minute deltas
        "ORDER_FLOW_IMBALANCE_FACTOR": 3, # Renamed from IMBALANCE_FACTOR for clarity here
        "ENTRY_PULLBACK_ATR_MULT": 0.25, # Micro-pullback depth <= 0.25 * ATR_H1
        "TP_R_MULTIPLE": 2.0, # TP = 2R
        "SCALE_OUT_R_MULTIPLE": 1.0, # Scale-out 1/3 @ 1R
        "SCALE_OUT_FRACTION": 1/3,
        "MAX_TRADE_RISK_PERCENT": 0.007, # 0.7% per trade
        "MAX_DAILY_DD_PERCENT": 0.03, # 3% daily DD
        "MAX_PORTFOLIO_HEAT_PERCENT": 0.01 # <= 1% portfolio heat
    }

    def __init__(self, params=None, risk_settings=None, account_info=None):
        """
        Initializes the strategy with specific parameters, risk settings, and account info.

        :param params: Dictionary of strategy-specific parameters.
        :param risk_settings: Dictionary of risk management settings.
                               For live trading, this comes from risk.models.RiskManagement.
                               For backtesting, this comes from BacktestConfig.risk_json.
        :param account_info: Dictionary containing account details like balance, equity.
        """
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.risk_settings = risk_settings or {}
        self.account_info = account_info or {}
        self.current_bias = None  # 'long', 'short', or None
        self.consecutive_losses = 0
        self.daily_drawdown = Decimal('0.0')
        self.portfolio_heat = Decimal('0.0') # Current total risk exposure

        # Internal state for tracking swings, ATR, etc.
        self.atr_h1 = None
        self.atr_15m = None # For BOS/ChoCH buffer
        self.prev_swing_high = None
        self.prev_swing_low = None
        self.last_higher_low = None # For ChoCH in uptrend
        self.last_lower_high = None # For ChoCH in downtrend
        
        # Order flow primitives state
        self.consecutive_bullish_imbalances = 0
        self.consecutive_bearish_imbalances = 0

        logger.info(f"FootprintV1Strategy initialized with params: {self.params}")
        logger.info(f"Risk settings: {self.risk_settings}")
        logger.info(f"Account info: {self.account_info}")

    def get_parameters_definition(self):
        """
        Returns a definition of the parameters this strategy uses,
        possibly with types, ranges, and descriptions.
        """
        return self.DEFAULT_PARAMS # Or a more detailed structure

    def _calculate_atr(self, historical_data, period):
        """
        Placeholder for ATR calculation.
        Requires historical high, low, close data.
        """
        # This would typically use a library like pandas_ta or a custom implementation
        logger.warning("ATR calculation is a placeholder.")
        if historical_data and len(historical_data) >= period:
            # Simplified ATR: average of true ranges for the last 'period' candles
            true_ranges = []
            for i in range(len(historical_data) - period, len(historical_data)):
                high = historical_data[i].get('high', 0)
                low = historical_data[i].get('low', 0)
                prev_close = historical_data[i-1].get('close', 0) if i > 0 else low
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                true_ranges.append(tr)
            return sum(true_ranges) / len(true_ranges) if true_ranges else Decimal('0.0001') # Avoid division by zero
        return Decimal('0.0001') # Default small value if not enough data

    def _update_indicators(self, market_data):
        """
        Updates internal indicators like ATR based on new market_data.
        `market_data` should contain necessary fields like 'close', 'high', 'low', 'volume',
        'h1_candles', 'm15_candles', 'm1_candles', 'ticks_raw'.
        """
        # Example: Update H1 ATR
        # self.atr_h1 = self._calculate_atr(market_data.get('h1_candles'), self.params["ATR_H1_LOOKBACK"])
        # self.atr_15m = self._calculate_atr(market_data.get('m15_candles'), some_lookback_for_15m) # Define lookback
        
        # For now, using placeholders if data isn't structured yet
        self.atr_h1 = market_data.get('atr_h1', Decimal('0.00500')) # Placeholder
        self.atr_15m = market_data.get('atr_15m', Decimal('0.00200')) # Placeholder
        logger.debug(f"Updated ATR H1: {self.atr_h1}, ATR 15m: {self.atr_15m}")


    def _determine_bias_state(self, market_data):
        """
        Implements BOS / ChoCH Logic from "Footprint Strategy Logic Deep Dive (1).pdf".
        `market_data` should contain 'close', 'low', 'high' for the 15-min timeframe,
        and historical swing points.
        """
        # Placeholder logic - requires proper swing point tracking and 15m candle data
        # close_15m = market_data.get('m15_close')
        # low_15m = market_data.get('m15_low')
        # high_15m = market_data.get('m15_high')

        # if not all([close_15m, low_15m, high_15m, self.atr_15m]):
        #     logger.warning("Missing data for bias determination.")
        #     return

        # buffer = max(Decimal(str(self.params["BOS_BUFFER"])) * close_15m, Decimal('0.2') * self.atr_15m)

        # # Logic for updating prev_swing_high, prev_swing_low, last_higher_low, last_lower_high
        # # This is complex and needs robust implementation based on price action.

        # is_bos_up = self.prev_swing_high and close_15m > self.prev_swing_high + buffer
        # is_bos_down = self.prev_swing_low and close_15m < self.prev_swing_low - buffer
        # is_choch_down = self.current_bias == 'long' and self.last_higher_low and low_15m < self.last_higher_low - buffer
        # is_choch_up = self.current_bias == 'short' and self.last_lower_high and high_15m > self.last_lower_high + buffer
        
        # if is_choch_down or is_choch_up:
        #     self.current_bias = None
        #     logger.info(f"ChoCH detected. Bias reset to None.")
        # elif is_bos_up:
        #     self.current_bias = 'long'
        #     logger.info(f"BOS Up detected. Bias set to Long.")
        # elif is_bos_down:
        #     self.current_bias = 'short'
        #     logger.info(f"BOS Down detected. Bias set to Short.")
        
        # For now, we'll cycle bias for testing if no real data feed
        if market_data.get("cycle_bias_for_test"):
            if self.current_bias == 'long': self.current_bias = 'short'
            elif self.current_bias == 'short': self.current_bias = None
            else: self.current_bias = 'long'
        logger.debug(f"Current Bias: {self.current_bias}")


    def _check_volume_gate(self, market_data):
        """
        Implements Vol Gate from "strategy engine.docx".
        Requires H1 ATR and its 90-day median.
        """
        # median_atr_h1_90day = market_data.get('median_atr_h1_90day') # This needs to be supplied
        # if self.atr_h1 and median_atr_h1_90day:
        #     if self.atr_h1 >= Decimal(str(self.params["VOL_GATE_ATR_MULT"])) * median_atr_h1_90day:
        #         return True
        # logger.info("Volume Gate: Not passed.")
        # return False
        logger.debug("Volume Gate: Placeholder - Assumed passed.")
        return True # Placeholder

    def _check_order_flow_confirmation(self, market_data):
        """
        Implements Order-Flow Confirm from "strategy engine.docx".
        Requires 1-minute delta data.
        `market_data` should include `m1_deltas` (list of {"delta": X, "buy_vol": Y, "sell_vol": Z})
        """
        # m1_deltas = market_data.get('m1_deltas', []) 
        # if len(m1_deltas) < self.params["ORDER_FLOW_CONFIRM_DELTAS"]:
        #     return False

        # recent_deltas = m1_deltas[-self.params["ORDER_FLOW_CONFIRM_DELTAS"]:]
        # confirmed_bullish = 0
        # confirmed_bearish = 0

        # for d in recent_deltas:
        #     delta = Decimal(str(d.get('delta', 0)))
        #     buy_vol = Decimal(str(d.get('buy_vol', 0)))
        #     sell_vol = Decimal(str(d.get('sell_vol', 0)))

        #     if self.current_bias == 'long':
        #         # Expecting bullish imbalance: delta > 0 and delta >= IMBALANCE_FACTOR * sell_vol
        #         if delta > 0 and sell_vol > 0 and (delta / sell_vol) >= Decimal(str(self.params["ORDER_FLOW_IMBALANCE_FACTOR"])):
        #             confirmed_bullish +=1
        #     elif self.current_bias == 'short':
        #         # Expecting bearish imbalance: delta < 0 and abs(delta) >= IMBALANCE_FACTOR * buy_vol
        #         if delta < 0 and buy_vol > 0 and (abs(delta) / buy_vol) >= Decimal(str(self.params["ORDER_FLOW_IMBALANCE_FACTOR"])):
        #             confirmed_bearish +=1
        
        # if self.current_bias == 'long' and confirmed_bullish == self.params["ORDER_FLOW_CONFIRM_DELTAS"]:
        #     logger.info("Order Flow Confirmed: Bullish")
        #     return True
        # if self.current_bias == 'short' and confirmed_bearish == self.params["ORDER_FLOW_CONFIRM_DELTAS"]:
        #     logger.info("Order Flow Confirmed: Bearish")
        #     return True
        
        # logger.debug("Order Flow Confirmation: Not met.")
        # return False
        logger.debug("Order Flow Confirmation: Placeholder - Assumed passed.")
        return True # Placeholder

    def _check_entry_micro_pullback(self, market_data):
        """
        Implements Entry (micro-pullback) from "strategy engine.docx" and "Footprint v1.1".
        Requires 1-min candle data, current bias, and impulse extreme.
        """
        # This is complex: needs to identify impulse, then first 1-min counter-bias close
        # that doesn't break impulse extreme, and depth <= 0.25 * ATR_H1.
        # m1_candles = market_data.get('m1_candles', [])
        # if not m1_candles or not self.atr_h1 or not self.current_bias:
        #     return None # Not enough data or no bias

        # # Simplified: assume last m1 candle is the pullback candle for placeholder
        # last_m1_candle = m1_candles[-1]
        # pullback_depth_ok = True # Placeholder: (abs(last_m1_candle['close'] - impulse_extreme_price) <= Decimal(str(self.params["ENTRY_PULLBACK_ATR_MULT"])) * self.atr_h1)
        # counter_bias_close_ok = True # Placeholder
        
        # if pullback_depth_ok and counter_bias_close_ok:
        #    entry_price = last_m1_candle['close']
        #    logger.info(f"Micro-pullback entry identified at {entry_price}")
        #    return entry_price
        # return None
        logger.debug("Micro-pullback: Placeholder - Assumed found.")
        return market_data.get('m1_close', Decimal('1.08000')) # Placeholder entry price

    def _calculate_sl_tp(self, entry_price, market_data):
        """
        Calculates SL and TP based on "strategy engine.docx" (Risk section).
        SL = last swing ± 0.25 × ATR_H1; TP = 2 R.
        """
        # if not self.atr_h1 or not entry_price: return None, None

        # sl_offset = Decimal(str(self.params["SL_ATR_MULT"])) * self.atr_h1
        # if self.current_bias == 'long':
        #     # SL below last swing low (or entry if no clear swing)
        #     sl_level = (self.last_higher_low or entry_price) - sl_offset 
        #     risk_per_unit = entry_price - sl_level
        #     tp_level = entry_price + risk_per_unit * Decimal(str(self.params["TP_R_MULTIPLE"]))
        # elif self.current_bias == 'short':
        #     # SL above last swing high (or entry)
        #     sl_level = (self.last_lower_high or entry_price) + sl_offset
        #     risk_per_unit = sl_level - entry_price
        #     tp_level = entry_price - risk_per_unit * Decimal(str(self.params["TP_R_MULTIPLE"]))
        # else:
        #     return None, None
        
        # if risk_per_unit <= 0: return None, None # Invalid risk

        # logger.info(f"Calculated SL: {sl_level}, TP: {tp_level}, Risk/Unit: {risk_per_unit}")
        # return sl_level, tp_level
        
        # Placeholder SL/TP
        sl_level = entry_price - Decimal('0.00100') if self.current_bias == 'long' else entry_price + Decimal('0.00100')
        tp_level = entry_price + Decimal('0.00200') if self.current_bias == 'long' else entry_price - Decimal('0.00200')
        logger.debug(f"Placeholder SL: {sl_level}, TP: {tp_level}")
        return sl_level, tp_level


    def _check_risk_guards(self, entry_price, sl_price, lot_size):
        """
        Checks guard-rails from "strategy engine.docx".
        0.7% per trade, 3% daily DD, 4 consecutive losses, <= 1% portfolio heat.
        """
        # account_balance = self.account_info.get('balance', Decimal('10000')) # Default for testing

        # # Max consecutive losses
        # if self.consecutive_losses >= self.params["MAX_CONSEC_LOSS"]:
        #     logger.warning(f"Risk Guard: Max consecutive losses ({self.params['MAX_CONSEC_LOSS']}) reached.")
        #     return False

        # # Per-trade risk
        # potential_loss_amount = abs(entry_price - sl_price) * lot_size * Decimal('100000') # Assuming standard lot for forex
        # trade_risk_pct = potential_loss_amount / account_balance
        # if trade_risk_pct > Decimal(str(self.params["MAX_TRADE_RISK_PERCENT"])):
        #     logger.warning(f"Risk Guard: Trade risk {trade_risk_pct:.4f} exceeds max {self.params['MAX_TRADE_RISK_PERCENT']}.")
        #     return False
        
        # # Daily DD (simplified, proper daily DD needs tracking P&L of closed trades for the day)
        # # This placeholder checks potential loss of current trade against daily DD limit
        # if (self.daily_drawdown + trade_risk_pct) > Decimal(str(self.params["MAX_DAILY_DD_PERCENT"])):
        #      logger.warning(f"Risk Guard: Potential daily DD exceeds limit.")
        #      return False

        # # Portfolio Heat (simplified, sum of risk % of all open trades)
        # # This placeholder checks current trade's risk against portfolio heat
        # if (self.portfolio_heat + trade_risk_pct) > Decimal(str(self.params["MAX_PORTFOLIO_HEAT_PERCENT"])):
        #      logger.warning(f"Risk Guard: Potential portfolio heat exceeds limit.")
        #      return False
        
        logger.debug("Risk Guards: Placeholder - Assumed passed.")
        return True # Placeholder

    def _calculate_lot_size(self, entry_price, sl_price):
        """
        Placeholder for lot size calculation based on risk settings.
        This should ideally use the existing `risk.services.calculate_position_size`.
        """
        # For now, a fixed lot size for testing
        # In reality:
        # risk_amount = account_balance * self.risk_settings.get('max_trade_risk_percent', 0.01)
        # risk_per_pip_atr = abs(entry_price - sl_price)
        # pip_value = ... (fetch from symbol info)
        # lot_size = risk_amount / (risk_per_pip_atr * pip_value)
        logger.debug("Lot Size: Placeholder - Using 0.01.")
        return Decimal('0.01') # Placeholder

    def run_tick(self, market_data, open_positions=None, account_details=None):
        """
        Main strategy logic execution for each tick/bar.

        :param market_data: A dictionary containing current and historical market data.
                            Example: {'symbol': 'EURUSD', 'timestamp': ...,
                                      'm1_close': 1.0800, 'm15_close': 1.0805, ...
                                      'h1_candles': [...], 'm1_deltas': [...],
                                      'atr_h1': 0.0050, 'median_atr_h1_90day': 0.0045}
        :param open_positions: List of current open positions for this strategy/account.
        :param account_details: Updated account details (balance, equity).
        :return: A list of actions (e.g., {'action': 'OPEN_TRADE', 'details': {...}}).
        """
        actions = []
        self.account_info = account_details or self.account_info # Update account info

        # 0. Edge Case Handling (from v1.1 doc)
        #    - Gap >= 3 * ATR_1h: Reset bias, pause 15 min. (Needs gap detection logic)
        #    - Delta missing/NaN: Skip bar, log warn. (Needs delta data structure)
        #    - Tick volume anomaly: Exclude from delta, mark. (Needs tick volume data)
        if market_data.get('gap_detected_large'): # Assuming this flag is set by data preprocessor
            self.current_bias = None
            # Logic to pause for 15 mins would be external to this call, or managed via state
            logger.warning("Large gap detected. Bias reset. Strategy paused (conceptual).")
            return actions
        if market_data.get('delta_missing_or_nan'):
            logger.warning("Delta missing or NaN for current bar. Skipping.")
            return actions

        # 1. Update Indicators (ATR etc.)
        self._update_indicators(market_data)

        # 2. Determine Bias (15-min BOS/ChoCH)
        self._determine_bias_state(market_data)
        if not self.current_bias:
            logger.info("No current bias. No new entry signals.")
            return actions

        # 3. Volatility Gate (H1 ATR vs 90-day median)
        if not self._check_volume_gate(market_data):
            logger.info("Volume gate not passed. No new entry signals.")
            return actions

        # 4. Order-Flow Confirmation (Two consecutive 1-min deltas)
        if not self._check_order_flow_confirmation(market_data):
            logger.info("Order flow confirmation not met. No new entry signals.")
            return actions

        # 5. Entry Logic (First micro-pullback)
        entry_price = self._check_entry_micro_pullback(market_data)
        if not entry_price:
            logger.info("No micro-pullback entry signal.")
            return actions

        # 6. Calculate SL & TP
        sl_price, tp_price = self._calculate_sl_tp(entry_price, market_data)
        if not sl_price or not tp_price:
            logger.warning("Could not calculate SL/TP. No trade.")
            return actions
            
        # 7. Calculate Lot Size (using risk parameters)
        lot_size = self._calculate_lot_size(entry_price, sl_price)
        if lot_size <= 0:
            logger.warning(f"Invalid lot size: {lot_size}. No trade.")
            return actions

        # 8. Risk Guard-Rails Check
        if not self._check_risk_guards(entry_price, sl_price, lot_size):
            logger.info("Risk guards prevent trade execution.")
            return actions

        # If all checks pass, generate trade signal
        trade_details = {
            'symbol': market_data.get('symbol', 'UNKNOWN_SYMBOL'),
            'direction': 'BUY' if self.current_bias == 'long' else 'SELL',
            'order_type': 'MARKET', # Or 'LIMIT' if entry_price is for a limit order
            'volume': lot_size,
            'price': entry_price, # For market, this might be indicative or not used by broker
            'stop_loss': sl_price,
            'take_profit': tp_price,
            # Add other relevant info like R-multiple, scale-out targets if applicable
            # 'scale_out_targets': [
            #    {'price': entry_price + (abs(entry_price-sl_price) * self.params["SCALE_OUT_R_MULTIPLE"]), 
            #     'volume_fraction': self.params["SCALE_OUT_FRACTION"]}
            # ] if self.current_bias == 'long' else [
            #    {'price': entry_price - (abs(entry_price-sl_price) * self.params["SCALE_OUT_R_MULTIPLE"]),
            #     'volume_fraction': self.params["SCALE_OUT_FRACTION"]}
            # ]
        }
        actions.append({'action': 'OPEN_TRADE', 'details': trade_details})
        logger.info(f"Generated OPEN_TRADE signal: {trade_details}")
        
        # Placeholder for managing open positions (e.g., trailing SL, partial TP)
        # This would iterate through `open_positions` and apply rules.
        # For example, if a TP or SL is hit based on `market_data['current_price']`.

        return actions

    def record_trade_result(self, won: bool, pnl: Decimal):
        """
        Called after a trade closes to update internal strategy state
        like consecutive losses, daily drawdown.
        """
        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        # self.daily_drawdown += pnl # This is too simple; needs proper daily equity tracking.
        logger.info(f"Trade result: {'Won' if won else 'Lost'}, PnL: {pnl}. Consecutive losses: {self.consecutive_losses}")

# Example Usage (for testing purposes)
if __name__ == '__main__':
    strategy = FootprintV1Strategy(params={"PIVOT_RANGE": 5}, risk_settings={"max_trade_risk_percent": 0.01})
    
    # Simulate some market data ticks
    # In a real scenario, market_data would be much richer and come from the data feed.
    sample_market_data_long_signal = {
        'symbol': 'EURUSD',
        'timestamp': '2023-01-01T10:00:00Z',
        'm1_close': Decimal('1.08000'),
        'atr_h1': Decimal('0.00500'),
        'median_atr_h1_90day': Decimal('0.00450'),
        'm1_deltas': [ # Assuming these satisfy order flow confirmation for long
            {'delta': 100, 'buy_vol': 150, 'sell_vol': 50},
            {'delta': 120, 'buy_vol': 160, 'sell_vol': 40},
        ],
        'cycle_bias_for_test': True # To force bias change for testing
    }
    
    print("\n--- Tick 1 ---")
    strategy.current_bias = None # Start with no bias
    actions = strategy.run_tick(sample_market_data_long_signal)
    print(f"Actions: {actions}")

    print("\n--- Tick 2 (assume bias is now long) ---")
    # strategy.current_bias = 'long' # Set by previous _determine_bias_state call
    actions = strategy.run_tick(sample_market_data_long_signal)
    print(f"Actions: {actions}")

    sample_market_data_short_signal = {
        'symbol': 'EURUSD',
        'timestamp': '2023-01-01T10:05:00Z',
        'm1_close': Decimal('1.07500'),
        'atr_h1': Decimal('0.00510'),
        'median_atr_h1_90day': Decimal('0.00450'),
         'm1_deltas': [ # Assuming these satisfy order flow confirmation for short
            {'delta': -100, 'buy_vol': 50, 'sell_vol': 150},
            {'delta': -120, 'buy_vol': 40, 'sell_vol': 160},
        ],
        'cycle_bias_for_test': True
    }
    print("\n--- Tick 3 (assume bias is now short) ---")
    # strategy.current_bias = 'short'
    actions = strategy.run_tick(sample_market_data_short_signal)
    print(f"Actions: {actions}")

    print("\n--- Tick 4 (assume bias is now None) ---")
    # strategy.current_bias = None
    actions = strategy.run_tick(sample_market_data_short_signal)
    print(f"Actions: {actions}")
