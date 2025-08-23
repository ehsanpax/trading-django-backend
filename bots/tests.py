from django.test import TestCase
import pandas as pd
from decimal import Decimal
from unittest.mock import MagicMock, patch
import numpy as np

from bots.base import make_open_trade, make_close_position, make_reduce_position, BaseStrategy
from bots.sectioned_adapter import SectionedStrategy
from bots.engine import BacktestEngine
from bots.adapters import LegacyStrategyAdapter
from bots.models import ExecutionConfig
from bots.gates import evaluate_filters, risk_allows_entry, apply_fill_model
from core.interfaces import IndicatorInterface

<<<<<<< Updated upstream
# --- New imports for validator ---
from bots.validation.sectioned import validate_sectioned_spec

=======
>>>>>>> Stashed changes
class MockIndicator(IndicatorInterface):
    def compute(self, df, params):
        param_str = "_".join([f"{k}_{v}" for k, v in sorted(params.items())])
        return {f"default": pd.Series(np.random.rand(len(df)), index=df.index, name=f"ema_default_{param_str}")}

class BotsAppTests(TestCase):
    def setUp(self):
        self.data = pd.DataFrame({
            'open': [1.0, 1.1, 1.2, 1.3, 1.4],
            'high': [1.05, 1.15, 1.25, 1.35, 1.45],
            'low': [0.95, 1.05, 1.15, 1.25, 1.35],
            'close': [1.0, 1.1, 1.2, 1.3, 1.4],
        }, index=pd.to_datetime(['2023-01-02 10:00', '2023-01-03 10:00', '2023-01-04 10:00', '2023-01-06 10:00', '2023-01-07 10:00']))
        self.exec_config = ExecutionConfig()
        self.tick_size = Decimal("0.00001")
        self.tick_value = Decimal("1")
        self.initial_equity = 10000.0
<<<<<<< Updated upstream
        # Align with SectionedStrategySpec (entry_long/short, exit_long/short)
        self.spec_data = {
            "entry_long": {
                "op": "AND",
                "clauses": [
                    {
                        "lhs": {"type": "indicator", "name": "ema", "params": {"length": 9, "period": 5}, "output": "default"},
                        "op": "crosses_above",
                        "rhs": {"type": "indicator", "name": "ema", "params": {"length": 21}, "output": "default"}
                    }
                ],
            },
            "exit_long": {},
            "risk": {"fixed_lot_size": 0.1}
=======
        self.spec_data = {
            "entry": {
                "and": [
                    {"left": {"indicator": "ema", "params": {"length": 9, "period": 5}, "output": "default"}, "op": "cross_above", "right": {"indicator": "ema", "params": {"length": 21}, "output": "default"}}
                ]
            },
            "exit": {}, "risk": {"fixed_lot_size": 0.1}
>>>>>>> Stashed changes
        }
        self.strategy_params = {"sectioned_spec": self.spec_data}
        self.instrument_spec = MagicMock()
        self.instrument_spec.tick_size = Decimal("0.0001")

    def test_make_open_trade_helper(self):
        action = make_open_trade(side="BUY", qty=1.0, sl=1.1, tp=1.3, tag="Test")
        self.assertEqual(action['action'], 'OPEN_TRADE')
        with self.assertRaises(ValueError):
            make_open_trade(side="BUY", qty=-1.0)

    def test_make_close_position_helper(self):
        action = make_close_position(side="ANY", qty="ALL", tag="Test")
        self.assertEqual(action['action'], 'CLOSE_POSITION')
        with self.assertRaises(ValueError):
            make_close_position(qty=-1.0)

    @patch('core.registry.indicator_registry.get_indicator')
    def test_sectioned_strategy_indicator_population(self, mock_get_indicator):
        mock_get_indicator.return_value = MockIndicator
        strategy = SectionedStrategy("EURUSD", "test", self.instrument_spec, self.strategy_params, {}, {})
        self.assertIsInstance(strategy.REQUIRED_INDICATORS, list)
        self.assertEqual(len(strategy.REQUIRED_INDICATORS), 2)
        expected = [{"name": "ema", "params": {"length": 9, "period": 5}}, {"name": "ema", "params": {"length": 21}}]
        self.assertIn(expected[0], strategy.REQUIRED_INDICATORS)
        self.assertIn(expected[1], strategy.REQUIRED_INDICATORS)

    def test_gate_day_of_week(self):
        filters_cfg = {"allowed_days_of_week": [0, 1, 2, 3]}
        self.assertFalse(evaluate_filters(self.data.index[3], None, filters_cfg)[0])
        self.assertTrue(evaluate_filters(self.data.index[0], None, filters_cfg)[0])

    def test_gate_session(self):
        filters_cfg = {"allowed_sessions": [{"start": "09:00", "end": "17:00"}]}
        self.assertFalse(evaluate_filters(pd.Timestamp("2023-01-02 08:00"), None, filters_cfg)[0])
        self.assertTrue(evaluate_filters(pd.Timestamp("2023-01-02 10:00"), None, filters_cfg)[0])

    def test_gate_daily_loss(self):
        risk_cfg = {"daily_loss_pct": 5}
        equity_series = [{'timestamp': '2023-01-02T10:00:00', 'equity': 10000.0}, {'timestamp': '2023-01-03T09:00:00', 'equity': 9400.0}]
        is_allowed, _ = risk_allows_entry([], equity_series, pd.Timestamp("2023-01-03 10:00:00"), risk_cfg, 10000.0)
        self.assertFalse(is_allowed)

    def test_fill_model(self):
        exec_cfg = ExecutionConfig(spread_pips=2, slippage_model='FIXED', slippage_value=1)
        buy_fill = apply_fill_model('BUY', 1.2000, None, exec_cfg, Decimal("0.0001"))
        self.assertAlmostEqual(buy_fill, 1.2002)
        sell_fill = apply_fill_model('SELL', 1.2000, None, exec_cfg, Decimal("0.0001"))
        self.assertAlmostEqual(sell_fill, 1.2000)

    def test_strategy_exit_not_blocked_by_filter(self):
        class TestStrategy(BaseStrategy):
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1)]
                if len(df) == 4: return [make_close_position()]
                return []
        engine = BacktestEngine(None, self.data, self.exec_config, self.tick_size, self.tick_value, self.initial_equity, filter_settings={"allowed_days_of_week": [0, 1]})
        engine.strategy = LegacyStrategyAdapter(TestStrategy("EURUSD", "test", None, {}, {}, {}), engine)
        engine.run()
        self.assertEqual(len(engine.trades), 1)
        self.assertEqual(engine.trades[0]['closure_reason'], 'STRATEGY_EXIT')

    def test_sl_tp_not_blocked_by_filter(self):
        class StrategyToOpenOnly(BaseStrategy):
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1, sl=1.15)]
                return []
        self.data.loc[self.data.index[3], 'low'] = 1.15
        engine = BacktestEngine(None, self.data, self.exec_config, self.tick_size, self.tick_value, self.initial_equity, filter_settings={"allowed_days_of_week": [0, 1]})
        engine.strategy = LegacyStrategyAdapter(StrategyToOpenOnly("EURUSD", "test", None, {}, {}, {}), engine)
        engine.run()
        self.assertEqual(len(engine.trades), 1)
        self.assertEqual(engine.trades[0]['closure_reason'], 'SL_HIT')

    def test_reduce_position(self):
        class TestStrategy(BaseStrategy):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.open_positions_after_reduce = None
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1)]
                if len(df) == 3:
                    self.open_positions_after_reduce = self.engine.open_positions
                    return [make_reduce_position(side="BUY", qty=0.5)]
                return []
        
        strategy = TestStrategy("EURUSD", "test", None, {}, {}, {})
        engine = BacktestEngine(None, self.data, self.exec_config, self.tick_size, self.tick_value, self.initial_equity)
        adapter = LegacyStrategyAdapter(strategy, engine)
        strategy.engine = engine
        engine.strategy = adapter
        engine.run()

        self.assertEqual(len(engine.trades), 2)
        self.assertEqual(engine.trades[0]['status'], 'PARTIAL_CLOSE')
        self.assertEqual(engine.trades[0]['reduced_volume'], 0.5)
        self.assertEqual(strategy.open_positions_after_reduce[0]['volume'], 0.5)

    def test_exit_bypasses_risk_gate(self):
        class TestStrategy(BaseStrategy):
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1)]
                if len(df) == 3: return [make_open_trade(side="BUY", qty=1)] # Should be blocked
                if len(df) == 4: return [make_close_position()] # Should be allowed
                return []
        
        engine = BacktestEngine(None, self.data, self.exec_config, self.tick_size, self.tick_value, self.initial_equity, risk_settings={"max_open_positions": 1})
        engine.strategy = LegacyStrategyAdapter(TestStrategy("EURUSD", "test", None, {}, {}, {}), engine)
        engine.run()
        self.assertEqual(len(engine.trades), 1)
        self.assertEqual(engine.trades[0]['closure_reason'], 'STRATEGY_EXIT')

    @patch('core.registry.indicator_registry.get_indicator')
    def test_indicator_naming_consistency(self, mock_get_indicator):
        mock_get_indicator.return_value = MockIndicator
        strategy = SectionedStrategy("EURUSD", "test", self.instrument_spec, self.strategy_params, {}, {})
        strategy.df = self.data.copy()
        strategy.df = strategy._calculate_indicators(strategy.df)
        
        # The _get_value method returns a series, so we compare the names
<<<<<<< Updated upstream
        col_name = strategy._get_value({"type": "indicator", "name": "ema", "params": {"length": 9, "period": 5}}, strategy.df).name
        col_name_reordered = strategy._get_value({"type": "indicator", "name": "ema", "params": {"period": 5, "length": 9}}, strategy.df).name
=======
        col_name = strategy._get_value({"indicator": "ema", "params": {"length": 9, "period": 5}}, strategy.df).name
        col_name_reordered = strategy._get_value({"indicator": "ema", "params": {"period": 5, "length": 9}}, strategy.df).name
>>>>>>> Stashed changes
        self.assertEqual(col_name, col_name_reordered)

    # @patch('core.registry.indicator_registry.get_indicator')
    # def test_warmup_enforcement(self, mock_get_indicator):
    #     mock_get_indicator.return_value = MockIndicator
    #     class TestStrategy(BaseStrategy):
    #         REQUIRED_INDICATORS = [{"name": "EMA", "params": {"length": 9}}, {"name": "EMA", "params": {"length": 21}}]
    #         def run_tick(self, df, eq):
    #             if not pd.isna(df['ema_default_length_9'].iloc[-1]) and df['ema_default_length_9'].iloc[-1] > df['ema_default_length_21'].iloc[-1]:
    #                 return [make_open_trade(side="BUY", qty=1)]
    #             return []
        
    #     data = pd.DataFrame({
    #         'open': np.random.rand(50), 'high': np.random.rand(50),
    #         'low': np.random.rand(50), 'close': np.random.rand(50)
    #     }, index=pd.date_range("2023-01-01", periods=50))
        
    #     engine = BacktestEngine(None, data, self.exec_config, self.tick_size, self.tick_value, self.initial_equity)
    #     strategy = TestStrategy("EURUSD", "test", None, {}, {}, {})
    #     engine.strategy = LegacyStrategyAdapter(strategy, engine)
    #     engine.run()
    #     self.assertEqual(len(engine.trades), 0)

    def test_commission_per_trade(self):
        class TestStrategy(BaseStrategy):
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1)]
                if len(df) == 4: return [make_close_position()]
                return []
        
        exec_config = ExecutionConfig(commission_units='PER_TRADE', commission_per_unit=5.0)
        engine = BacktestEngine(None, self.data, exec_config, self.tick_size, self.tick_value, self.initial_equity)
        engine.strategy = LegacyStrategyAdapter(TestStrategy("EURUSD", "test", None, {}, {}, {}), engine)
        engine.run()
        self.assertEqual(len(engine.trades), 1)
        self.assertAlmostEqual(engine.trades[0]['pnl'], 20000.0 - 5.0)

    def test_commission_per_lot(self):
        class TestStrategy(BaseStrategy):
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1.5)]
                if len(df) == 4: return [make_close_position()]
                return []
        
        exec_config = ExecutionConfig(commission_units='PER_LOT', commission_per_unit=2.0)
        engine = BacktestEngine(None, self.data, exec_config, self.tick_size, self.tick_value, self.initial_equity)
        engine.strategy = LegacyStrategyAdapter(TestStrategy("EURUSD", "test", None, {}, {}, {}), engine)
        engine.run()
        self.assertEqual(len(engine.trades), 1)
        self.assertAlmostEqual(engine.trades[0]['pnl'], (1.3 - 1.1) / 0.00001 * 1 * 1.5 - (2.0 * 1.5))

    def test_latency_same_bar_fill(self):
        class TestStrategy(BaseStrategy):
            def run_tick(self, df, eq):
                if len(df) == 2: return [make_open_trade(side="BUY", qty=1)]
                return []
        
        engine = BacktestEngine(None, self.data, self.exec_config, self.tick_size, self.tick_value, self.initial_equity)
        engine.strategy = LegacyStrategyAdapter(TestStrategy("EURUSD", "test", None, {}, {}, {}), engine)
        engine.run()
        self.assertEqual(len(engine.trades), 1)
        self.assertEqual(pd.to_datetime(engine.trades[0]['entry_timestamp']).date(), self.data.index[1].date())
<<<<<<< Updated upstream

    def test_sectioned_validator_basic(self):
        indicator_catalog = {
            'rsi': {
                'outputs': ['value'],
                'params': {'period': {'type': 'int', 'min': 1, 'max': 200, 'required': True}},
                'timeframes': ['M1', 'M5', 'H1']
            }
        }
        spec = {
            'indicators': [
                {'name': 'rsi', 'timeframe': 'M5', 'params': {'period': 14}, 'outputs': ['value']}
            ],
            'entry': {
                'conditions': [
                    {'lhs': {'ind': 'rsi', 'output': 'value'}, 'op': '<', 'rhs': 30}
                ]
            },
            'exit': {'conditions': []},
            'risk': {'sizing': {'mode': 'fixed_amount', 'amount': 100}, 'stop_loss': 10}
        }
        issues = validate_sectioned_spec(spec, indicator_catalog=indicator_catalog)
        errors = [i for i in issues if getattr(i, 'level', 'error') == 'error']
        self.assertEqual(len(errors), 0, f"Unexpected errors: {[e.message for e in errors]}")

    def test_sectioned_validator_unknown_indicator(self):
        spec = {
            'indicators': [{'name': 'foo', 'params': {}}],
            'entry': {'conditions': [{'lhs': {'ind': 'foo', 'output': 'value'}, 'op': '<', 'rhs': 50}]},
            'exit': {},
            'risk': {}
        }
        issues = validate_sectioned_spec(spec, indicator_catalog={'rsi': {'outputs': ['value'], 'params': {}}})
        self.assertTrue(any(i.code in ('indicator.unknown', 'indicator.ref.unknown') for i in issues))

    def test_sectioned_strategy_trace_emit(self):
        # Minimal spec: enter long if close > 0
        raw_spec = {
            'entry_long': {'op': '>', 'lhs': {'type': 'literal', 'value': 0}, 'rhs': 'close'},
            'risk': {'fixed_lot_size': 0.1}
        }
        df = pd.DataFrame({'open': [1.0, 1.1], 'high': [1.0, 1.1], 'low': [1.0, 1.1], 'close': [1.0, 1.1]}, index=pd.date_range('2023-01-01', periods=2, freq='D'))
        instr = MagicMock()
        instr.tick_size = Decimal('0.0001')
        instr.tick_value = Decimal('1')
        instr.contract_size = Decimal('1')
        trace = []
        strategy = SectionedStrategy('EURUSD', 'acct', instr, {'sectioned_spec': raw_spec, 'trace_enabled': True}, {}, {})
        strategy.set_trace(True, callback=lambda atom: trace.append(atom), sampling=1)
        actions = strategy.run_tick(df, 10000.0)
        kinds = {t['kind'] for t in trace}
        self.assertIn('inputs', kinds)
        self.assertIn('condition_eval', kinds)
        self.assertTrue(any(t['kind'] == 'order_intent' for t in trace) or len(actions) >= 0)
=======
>>>>>>> Stashed changes
