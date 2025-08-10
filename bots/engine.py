import pandas as pd
import logging
import uuid
from decimal import Decimal

from core.interfaces import StrategyInterface
from bots.models import ExecutionConfig

logger = logging.getLogger(__name__)

from bots.gates import evaluate_filters, risk_allows_entry, apply_fill_model

class BacktestEngine:
    """
    An event-driven backtesting engine with realistic execution simulation.
    """
    def __init__(self, strategy: StrategyInterface, data: pd.DataFrame, execution_config: ExecutionConfig, tick_size: Decimal, tick_value: Decimal, initial_equity: float, risk_settings: dict = None, filter_settings: dict = None):
        self.strategy = strategy
        self.data = data
        self.execution_config = execution_config
        self.tick_size = tick_size
        self.tick_value = tick_value
        self.initial_equity = initial_equity
        self.risk_settings = risk_settings if risk_settings is not None else {}
        self.filter_settings = filter_settings if filter_settings is not None else {}
        
        self.current_bar = 0
        self.equity = initial_equity
        self.equity_curve = []
        self.trades = []
        self.open_positions = []

    def run(self):
        """
        Runs the backtest simulation.
        """
        self.equity_curve.append({'timestamp': self.data.index[0].isoformat(), 'equity': self.equity})

        for i in range(len(self.data)):
            self.current_bar = i
            current_window = self.data.iloc[:i+1]
            current_bar_data = self.data.iloc[i]
            
            # 1. Update open positions for SL/TP hits
            self._check_sl_tp(current_bar_data)
            
            # 2. Evaluate filters
            eligible, filter_reason = evaluate_filters(current_bar_data.name, current_bar_data, self.filter_settings)
            
            # 3. Get strategy actions
            actions = self.strategy.on_bar_close(current_window)
            
            # 4. Process actions
            if actions:
                self._process_actions(actions, current_bar_data, eligible, filter_reason)
            
            # 5. Record equity point
            self.equity_curve.append({'timestamp': current_bar_data.name.isoformat(), 'equity': round(self.equity, 2)})

        self._close_open_positions(self.data.iloc[-1])
        logger.info("Backtest finished.")

    def _check_sl_tp(self, current_bar):
        positions_to_remove = []
        for pos in self.open_positions:
            pos_closed = False
            exit_price = None
            closure_reason = None

            low = Decimal(str(current_bar['low']))
            high = Decimal(str(current_bar['high']))

            if pos['direction'] == 'BUY':
                # Check Stop Loss
                if pos.get('stop_loss') is not None:
                    sl = Decimal(str(pos['stop_loss']))
                    if low <= sl:
                        pos_closed = True
                        exit_price = sl
                        closure_reason = 'SL_HIT'
                # Check Take Profit
                if not pos_closed and pos.get('take_profit') is not None:
                    tp = Decimal(str(pos['take_profit']))
                    if high >= tp:
                        pos_closed = True
                        exit_price = tp
                        closure_reason = 'TP_HIT'
            
            elif pos['direction'] == 'SELL':
                # Check Stop Loss
                if pos.get('stop_loss') is not None:
                    sl = Decimal(str(pos['stop_loss']))
                    if high >= sl:
                        pos_closed = True
                        exit_price = sl
                        closure_reason = 'SL_HIT'
                # Check Take Profit
                if not pos_closed and pos.get('take_profit') is not None:
                    tp = Decimal(str(pos['take_profit']))
                    if low <= tp:
                        pos_closed = True
                        exit_price = tp
                        closure_reason = 'TP_HIT'

            if pos_closed:
                self._close_position(pos, exit_price, current_bar.name, closure_reason)
                positions_to_remove.append(pos)

        self.open_positions = [p for p in self.open_positions if p not in positions_to_remove]
    
    def _close_position(self, pos, exit_price, exit_timestamp, closure_reason):
        entry_price = Decimal(str(pos['entry_price']))
        volume = Decimal(str(pos['volume']))
        exit_price = Decimal(str(exit_price)) # Ensure exit_price is also a Decimal
        
        pnl = Decimal('0.0')
        if self.tick_size > 0:
            if pos['direction'] == 'BUY':
                price_diff_ticks = (exit_price - entry_price) / self.tick_size
            else: # SELL
                price_diff_ticks = (entry_price - exit_price) / self.tick_size
            pnl = price_diff_ticks * self.tick_value * volume

        if self.execution_config:
            if self.execution_config.commission_units == 'PER_TRADE':
                pnl -= self.execution_config.commission_per_unit
            elif self.execution_config.commission_units == 'PER_LOT':
                pnl -= self.execution_config.commission_per_unit * volume
        
        self.equity += float(pnl)
        
        closed_trade = {
            **pos,
            'exit_price': float(exit_price),
            'exit_timestamp': exit_timestamp.isoformat(),
            'pnl': float(pnl),
            'status': 'CLOSED',
            'closure_reason': closure_reason
        }
        self.trades.append(closed_trade)
        logger.info(f"Sim CLOSE: {pos['direction']} {pos['volume']} @{pos['entry_price']} by {closure_reason} @{exit_price}. P&L: {pnl:.2f}. Equity: {self.equity:.2f}")

    def _close_open_positions(self, last_bar):
        if not self.open_positions:
            return
        
        logger.info(f"End of backtest: Closing {len(self.open_positions)} remaining open positions.")
        last_price = Decimal(str(last_bar['close']))
        for pos in list(self.open_positions):
            self._close_position(pos, last_price, last_bar.name, 'END_OF_BACKTEST')
        self.open_positions = []

    def _process_actions(self, actions, bar_data, eligible, filter_reason):
        for action in actions:
            action_type = action.get('action')
            
            if action_type == 'OPEN_TRADE':
                if not eligible:
                    logger.info(f"Entry skipped due to filter: {filter_reason}")
                    continue
                
                # Risk gates only apply to new entries
                ok, risk_reason = risk_allows_entry(self.open_positions, self.equity_curve, bar_data.name, self.risk_settings, self.initial_equity)
                if not ok:
                    logger.info(f"Entry skipped due to risk guard: {risk_reason}")
                    continue
                
                self._open_trade(action, bar_data)

            elif action_type == 'CLOSE_POSITION':
                # Exits should bypass filters
                self._handle_close_position(action, bar_data)
            
            elif action_type == 'REDUCE_POSITION':
                # Exits should bypass filters
                self._handle_reduce_position(action, bar_data)
                
            elif action_type == 'MODIFY_SLTP':
                self._handle_modify_sltp(action)

    def _open_trade(self, action, bar_data):
        intended_price = Decimal(str(bar_data['close'])) # Assume entry at close for now
        direction = action['side'].upper()
        
        fill_price = self.apply_fill_model(direction, intended_price, bar_data, self.execution_config)

        new_pos = {
            'id': str(uuid.uuid4()),
            'intended_price': float(intended_price),
            'entry_price': float(fill_price),
            'volume': float(action['qty']),
            'direction': direction,
            'stop_loss': float(action['sl']) if action.get('sl') else None,
            'take_profit': float(action['tp']) if action.get('tp') else None,
            'entry_timestamp': bar_data.name.isoformat(),
            'symbol': self.strategy.legacy_strategy.instrument_symbol, # Bit of a hack to get the symbol
            'comment': action.get('tag', '')
        }
        self.open_positions.append(new_pos)
        logger.info(f"Sim OPEN: {new_pos['direction']} {new_pos['volume']} @{new_pos['entry_price']} (intended: {intended_price})")

    def _handle_close_position(self, action, bar_data):
        positions_to_close = []
        side_to_close = action.get('side', 'ANY').upper()
        
        for pos in self.open_positions:
            if side_to_close == 'ANY' or pos['direction'] == side_to_close:
                positions_to_close.append(pos)
        
        for pos in positions_to_close:
            # Assume close at the current bar's close price
            intended_price = Decimal(str(bar_data['close']))
            fill_price = self.apply_fill_model(pos['direction'], intended_price, bar_data, self.execution_config)
            closure_reason = action.get('tag') or 'STRATEGY_EXIT'
            self._close_position(pos, fill_price, bar_data.name, closure_reason)
            self.open_positions.remove(pos)

    def _handle_reduce_position(self, action, bar_data):
        qty_to_reduce = Decimal(str(action['qty']))
        side = action.get('side', 'BUY').upper()

        for pos in list(self.open_positions):  # FIFO
            if pos['direction'] != side:
                continue
            reduce_now = min(Decimal(str(pos['volume'])), qty_to_reduce)
            if reduce_now <= 0:
                break

            intended_price = Decimal(str(bar_data['close']))
            fill_price = Decimal(str(self.apply_fill_model(side, intended_price, bar_data, self.execution_config)))

            # realize partial pnl
            entry_price = Decimal(str(pos['entry_price']))
            pnl_ticks = ((fill_price - entry_price) / self.tick_size) if side == 'BUY' else ((entry_price - fill_price) / self.tick_size)
            pnl = pnl_ticks * self.tick_value * reduce_now

            # commissions (optional, same as close)
            if self.execution_config:
                if self.execution_config.commission_units == 'PER_TRADE':
                    pnl -= self.execution_config.commission_per_unit
                elif self.execution_config.commission_units == 'PER_LOT':
                    pnl -= self.execution_config.commission_per_unit * reduce_now

            self.equity += float(pnl)
            pos['volume'] = float(Decimal(str(pos['volume'])) - reduce_now)

            self.trades.append({
                **pos,  # snapshot-ish
                'exit_price': float(fill_price),
                'exit_timestamp': bar_data.name.isoformat(),
                'pnl': float(pnl),
                'status': 'PARTIAL_CLOSE',
                'closure_reason': 'REDUCE_SIGNAL',
                'reduced_volume': float(reduce_now),
            })

            if Decimal(str(pos['volume'])) <= 0:
                self.open_positions.remove(pos)

            qty_to_reduce -= reduce_now
            if qty_to_reduce <= 0:
                break

    def _handle_modify_sltp(self, action):
        side_to_modify = action.get('side', 'ANY').upper()
        for pos in self.open_positions:
            if side_to_modify == 'ANY' or pos['direction'] == side_to_modify:
                if action.get('sl') is not None:
                    pos['stop_loss'] = float(action['sl'])
                if action.get('tp') is not None:
                    pos['take_profit'] = float(action['tp'])
                logger.info(f"Sim MODIFY SL/TP for position {pos['id']}: SL={pos['stop_loss']}, TP={pos['take_profit']}")

    def apply_fill_model(self, side: str, intended_price: Decimal, bar: pd.Series, cfg: ExecutionConfig) -> Decimal:
        return apply_fill_model(side, float(intended_price), bar, cfg, self.tick_size)
