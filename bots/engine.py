import pandas as pd
import logging
import uuid
from decimal import Decimal
from typing import Optional, Dict, Any, List

from django.db import transaction
from django.conf import settings

from core.interfaces import StrategyInterface
from bots.models import ExecutionConfig, BacktestDecisionTrace, BacktestRun
from bots.gates import evaluate_filters, risk_allows_entry, apply_fill_model

logger = logging.getLogger(__name__)

class BacktestEngine:
    """
    An event-driven backtesting engine with realistic execution simulation.
    """
    def __init__(
        self,
        strategy: StrategyInterface,
        data: pd.DataFrame,
        execution_config: ExecutionConfig,
        tick_size: Decimal,
        tick_value: Decimal,
        initial_equity: float,
        risk_settings: dict = None,
        filter_settings: dict = None,
        # Tracing options (optional)
        trace_enabled: bool = False,
        trace_sampling: int = 1,
        backtest_run: Optional[BacktestRun] = None,
        trace_symbol: Optional[str] = None,
        trace_timeframe: Optional[str] = None,
    ):
        self.strategy = strategy
        self.data = data
        self.execution_config = execution_config
        self.tick_size = tick_size
        self.tick_value = tick_value
        self.initial_equity = initial_equity
        self.risk_settings = risk_settings if risk_settings is not None else {}
        self.filter_settings = filter_settings if filter_settings is not None else {}
        # Trace state
        self._trace_enabled = bool(trace_enabled)
        self._trace_sampling = max(1, int(trace_sampling or 1))
        self._trace_atoms: List[Dict[str, Any]] = []
        self._trace_bar_counts: Dict[int, int] = {}
        self._backtest_run = backtest_run
        # Derive defaults
        self._trace_symbol = trace_symbol or getattr(getattr(self.strategy, 'legacy_strategy', None), 'instrument_symbol', None) or ''
        self._trace_timeframe = trace_timeframe or 'M1'
        # Caps & batching from settings
        self._trace_max_rows = int(getattr(settings, 'BOTS_TRACE_MAX_ROWS', 250_000))
        self._trace_batch_size = int(getattr(settings, 'BOTS_TRACE_BATCH_SIZE', 1000))
        self._trace_truncated = False

        self.current_bar = 0
        self.equity = initial_equity
        self.equity_curve = []
        self.trades = []
        self.open_positions = []

    def run(self):
        """
        Runs the backtest simulation.
        """
        # If strategy supports tracing, wire callback (prefers legacy_strategy if using adapter)
        try:
            target = getattr(self.strategy, 'legacy_strategy', self.strategy)
            if self._trace_enabled and hasattr(target, 'set_trace') and callable(getattr(target, 'set_trace')):
                target.set_trace(True, callback=self._collect_trace, sampling=self._trace_sampling)
        except Exception:
            logger.debug("Trace setup failed", exc_info=True)

        self.equity_curve.append({'timestamp': self.data.index[0].isoformat(), 'equity': self.equity})

        for i in range(len(self.data)):
            self.current_bar = i
            current_window = self.data.iloc[:i+1]
            current_bar_data = self.data.iloc[i]

            # 1. Update open positions for SL/TP hits
            self._check_sl_tp(current_bar_data)

            # 2. Evaluate filters
            eligible, filter_reason = evaluate_filters(current_bar_data.name, current_bar_data, self.filter_settings)
            self._emit_engine_trace('filter', 'result', {'eligible': bool(eligible), 'reason': filter_reason}, current_bar_data)

            # 3. Get strategy actions
            actions = self.strategy.on_bar_close(current_window)

            # 4. Process actions
            if actions:
                self._process_actions(actions, current_bar_data, eligible, filter_reason)

            # 5. Record equity point
            self.equity_curve.append({'timestamp': current_bar_data.name.isoformat(), 'equity': round(self.equity, 2)})

        self._close_open_positions(self.data.iloc[-1])
        # Persist traces at the end
        self._persist_traces()
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
        exit_price = Decimal(str(exit_price))  # Ensure exit_price is also a Decimal

        pnl = Decimal('0.0')
        if self.tick_size > 0:
            if pos['direction'] == 'BUY':
                price_diff_ticks = (exit_price - entry_price) / self.tick_size
            else:  # SELL
                price_diff_ticks = (entry_price - exit_price) / self.tick_size
            pnl = price_diff_ticks * self.tick_value * volume

        if self.execution_config:
            commission = Decimal(str(self.execution_config.commission_per_unit or '0'))
            if self.execution_config.commission_units == 'PER_TRADE':
                pnl -= commission
            elif self.execution_config.commission_units == 'PER_LOT':
                pnl -= commission * volume

        self.equity += float(pnl)

        closed_trade = {
            **pos,
            'exit_price': float(exit_price),
            'exit_timestamp': exit_timestamp.isoformat() if hasattr(exit_timestamp, 'isoformat') else str(exit_timestamp),
            'pnl': float(pnl),
            'status': 'CLOSED',
            'closure_reason': closure_reason
        }
        self.trades.append(closed_trade)
        # Engine trace for exit
        self._emit_engine_trace('fill', 'exit', {
            'pos_id': pos.get('id'),
            'side': pos.get('direction'),
            'exit_price': float(exit_price),
            'reason': closure_reason,
            'pnl': float(pnl),
        }, None, ts=exit_timestamp)
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
                    self._emit_engine_trace('filter', 'blocked', {'reason': filter_reason}, bar_data)
                    continue

                # Risk gates only apply to new entries
                ok, risk_reason = risk_allows_entry(self.open_positions, self.equity_curve, bar_data.name, self.risk_settings, self.initial_equity)
                if not ok:
                    logger.info(f"Entry skipped due to risk guard: {risk_reason}")
                    self._emit_engine_trace('risk', 'blocked', {'reason': risk_reason}, bar_data)
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
        intended_price = Decimal(str(bar_data['close']))  # Assume entry at close for now
        direction = action['side'].upper()

        fill_price = self.apply_fill_model(direction, intended_price, bar_data, self.execution_config)
        fill_price_dec = Decimal(str(fill_price))

        # Derive TP from rr_ratio/default_rr when tp is missing but sl is provided
        sl_dec = Decimal(str(action['sl'])) if action.get('sl') is not None else None
        tp_dec = None
        if action.get('tp') is not None:
            tp_dec = Decimal(str(action.get('tp')))
        elif sl_dec is not None:
            # Determine RR: prefer action.rr_ratio, then engine risk_settings.default_rr, fallback 2.0
            rr = action.get('rr_ratio')
            try:
                rr = float(rr) if rr is not None else float(self.risk_settings.get('default_rr', 2.0))
            except Exception:
                rr = 2.0
            if rr and rr > 0:
                price_sl_distance = abs(fill_price_dec - sl_dec)
                if price_sl_distance > 0:
                    if direction == 'BUY':
                        tp_dec = fill_price_dec + Decimal(str(rr)) * price_sl_distance
                    else:  # SELL
                        tp_dec = fill_price_dec - Decimal(str(rr)) * price_sl_distance
                    logger.info(f"Derived TP for backtest using RR={rr}: entry={fill_price_dec}, SL_dist={price_sl_distance} -> TP={tp_dec}")

        new_pos = {
            'id': str(uuid.uuid4()),
            'intended_price': float(intended_price),
            'entry_price': float(fill_price_dec),
            'volume': float(action['qty']),
            'direction': direction,
            'stop_loss': float(sl_dec) if sl_dec is not None else None,
            'take_profit': float(tp_dec) if tp_dec is not None else (float(action['tp']) if action.get('tp') is not None else None),
            'entry_timestamp': bar_data.name.isoformat(),
            'symbol': self.strategy.legacy_strategy.instrument_symbol,  # Bit of a hack to get the symbol
            'comment': action.get('tag', '')
        }
        self.open_positions.append(new_pos)
        # Engine trace for entry
        self._emit_engine_trace('fill', 'entry', {
            'pos_id': new_pos['id'],
            'side': direction,
            'entry_price': float(fill_price_dec),
            'sl': float(sl_dec) if sl_dec is not None else None,
            'tp': float(tp_dec) if tp_dec is not None else (float(action['tp']) if action.get('tp') is not None else None),
        }, bar_data)
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
                commission = Decimal(str(self.execution_config.commission_per_unit or '0'))
                if self.execution_config.commission_units == 'PER_TRADE':
                    pnl -= commission
                elif self.execution_config.commission_units == 'PER_LOT':
                    pnl -= commission * reduce_now

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
            # Engine trace for reduce
            self._emit_engine_trace('fill', 'reduce', {
                'pos_id': pos.get('id'),
                'side': side,
                'exit_price': float(fill_price),
                'reduced_volume': float(reduce_now),
                'pnl': float(pnl),
            }, bar_data)

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
                # Engine trace for modify
                self._emit_engine_trace('fill', 'modify_sltp', {
                    'pos_id': pos.get('id'),
                    'sl': pos.get('stop_loss'),
                    'tp': pos.get('take_profit'),
                }, None)

    def apply_fill_model(self, side: str, intended_price: Decimal, bar: pd.Series, cfg: ExecutionConfig) -> Decimal:
        return apply_fill_model(side, float(intended_price), bar, cfg, self.tick_size)

    # --- Tracing helpers ---
    def _emit_engine_trace(self, section: str, kind: str, payload: Dict[str, Any] | None, bar_data: Optional[pd.Series] = None, ts=None):
        """Safely emit a trace atom from the engine/gates. No-ops if tracing is disabled."""
        if not self._trace_enabled:
            return
        try:
            atom: Dict[str, Any] = {
                'section': section,
                'kind': kind,
                'payload': payload or {},
            }
            # Provide ts when available; _collect_trace will also fill if missing
            if ts is None and bar_data is not None:
                ts = getattr(bar_data, 'name', None)
            if ts is not None:
                try:
                    atom['ts'] = ts.isoformat() if hasattr(ts, 'isoformat') else ts
                except Exception:
                    atom['ts'] = str(ts)
            self._collect_trace(atom)
        except Exception:
            logger.debug('Engine emit trace failed', exc_info=True)

    def _collect_trace(self, atom: Dict[str, Any]):
        if not self._trace_enabled:
            return
        # Cap total rows
        if len(self._trace_atoms) >= self._trace_max_rows:
            if not self._trace_truncated:
                self._trace_truncated = True
                logger.warning("Trace cap reached; further atoms will be dropped (max=%s)", self._trace_max_rows)
            return
        try:
            # Ensure ts and bar_index
            ts = atom.get('ts')
            bar_index = atom.get('bar_index')
            if ts is None and 0 <= self.current_bar < len(self.data.index):
                ts = self.data.index[self.current_bar]
                try:
                    atom['ts'] = ts.isoformat()
                except Exception:
                    atom['ts'] = str(ts)
            if bar_index is None:
                bar_index = self.current_bar
                atom['bar_index'] = bar_index
            # idx per bar
            self._trace_bar_counts[bar_index] = self._trace_bar_counts.get(bar_index, 0) + 1
            atom['idx'] = self._trace_bar_counts[bar_index]
            # annotate symbol/timeframe
            atom['symbol'] = atom.get('symbol') or self._trace_symbol or ''
            atom['timeframe'] = atom.get('timeframe') or self._trace_timeframe or 'M1'
            self._trace_atoms.append(atom)
        except Exception:
            logger.debug('Trace collect failed', exc_info=True)

    def _persist_traces(self):
        if not self._trace_enabled or not self._backtest_run or not self._trace_atoms:
            return
        try:
            # Enforce hard cap on what we write
            atoms = self._trace_atoms[: self._trace_max_rows]
            # Build model instances
            objs: List[BacktestDecisionTrace] = []
            for a in atoms:
                ts_val = a.get('ts')
                # Normalize ts
                if isinstance(ts_val, str):
                    ts_parsed = pd.Timestamp(ts_val).to_pydatetime()
                else:
                    ts_parsed = ts_val
                objs.append(BacktestDecisionTrace(
                    backtest_run=self._backtest_run,
                    ts=ts_parsed,
                    bar_index=int(a.get('bar_index', 0)),
                    symbol=str(a.get('symbol') or ''),
                    timeframe=str(a.get('timeframe') or 'M1'),
                    section=str(a.get('section') or ''),
                    kind=str(a.get('kind') or ''),
                    payload=a.get('payload') or {},
                    idx=a.get('idx'),
                ))
            if not objs:
                return
            # Bulk-create in batches from settings
            batch = self._trace_batch_size
            with transaction.atomic():
                for i in range(0, len(objs), batch):
                    BacktestDecisionTrace.objects.bulk_create(objs[i:i+batch])
            logger.info("Persisted %s decision trace atoms for run %s%s",
                        len(objs), getattr(self._backtest_run, 'id', ''),
                        " (truncated)" if self._trace_truncated else "")
        except Exception:
            logger.error('Trace persistence failed', exc_info=True)
